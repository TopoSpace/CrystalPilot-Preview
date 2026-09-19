# ka1-org 泳道核读：纯工具臂 vs 全栈臂

> 对象：N-(3-oxobutanoyl)-L-homoserine lactone（C8H11NO4，P2₁2₁2₁，Cu Kα，COD 2241460；
> 参考 R1 0.0264 @ 0.805 Å）。数据 `H:/CrystalPilotData/staging/ka1o/`：`crystal.hkl` 由沉积
> fcf 反推，**系统消光类反射在文件里根本不存在**，外加冷启动 `start.ins`（CELL/ZERR/
> LATT -1/SFAC C H N O/UNIT 1 1 1 1，无 SYMM）。两臂同一模型（gpt-5.6-sol, effort xhigh）、
> 同一条 L0 提示（"数据目录（只读）：… 请解这个结构。"），只差 AGENTS.md：
> 纯工具臂 = `TEMPLATE_TOOLS_ONLY`（3 691 B，只有操作契约+诚实守则，无判断规则、无阈值、
> 无技能卡指针，四个技能工具未注册，工具数 65）；全栈臂 = `TEMPLATE` v32（26 445 B，
> 工具图谱+判断规则+技能卡指针，工具数 69）。两份 AGENTS.md 的 sha256 均与模板一致
> （`state.json: agents_matches_template=true`）。
>
> **时钟约定**：本文所有 "x.xx min" 均为**距该格首次工具调用**的分钟数（rollout 的
> `function_call`/`custom_tool_call`/`mcp_tool_call_end` 统一时间轴）。绝对时刻用本地时间
> （rollout 时间戳为 UTC，本机 +8）。
>
> **口径**：全部取自 `logs/rollout.jsonl`（agent 推理 + 每次工具调用的完整参数 + 完整返回）
> 与 `grade.json`；机械指标先过 `crystalpilot/benchmark/campaign_analysis.py::analyse_case`
> （`staging_allow=["H:/CrystalPilotData/staging/ka1o"]`：两臂 `leak_clean=true`、
> `shell_hazards=[]`、`path_token_cited=false`）。

| 格 | 臂 | 等级 | R1 | d_min | 墙钟 | tokens | 工具调用 | 其中 MCP | 失败 |
|---|---|---|---|---|---|---|---|---|---|
| org-tools-r1 | 纯工具 | **no_delivery** | — | — | 7 224 s（超时中断） | 7.08 M | 171（136 次 `wait`、20 次 `exec`） | **15** | 5 |
| org-full-r1 | 全栈 | **publication** | 0.0263 | 0.8049 | 1 042 s（17.4 min） | 9.33 M | 155（8 次 `wait`、72 次 `exec`） | **75** | 3 |

> ⚠️ **两处需要更新现场笔记**：
> 1. `grade.json`（22:55:36 生成，酰胺 N 假阳性修复后的重评）已把 org-full-r1 判为
>    **publication**，`chemistry.flags=[]`、`blocking_model_quality=[]`、`gate_d_pass=true`，
>    `grade_reasons` 只剩"metadata incomplete（183/184/185/699，不计分）"。
>    `state.json` 里仍写 `"grade": "acceptable"`（18:14 写入），**state.json 已过期**。
> 2. 纯工具臂**并非"哑掉"**：主回合在 17:55:43 被 7 200 s 案例超时以 `interrupted` 掐断
>    （`turn_aborted … duration_ms 7212300`）后，runner 又发了收尾提问
>    （"战役收尾：请按输出 schema 给出最终裁决（不做新的精修动作，如实汇报当前状态）。"），
>    agent 8 s 内给出**完全诚实的裁决**：
>    `{"solved":false,"space_group":null,"n_atoms":0,"delivered":false,"unresolved":["结构求解未完成","空间群尚未由结构模型验证","未获得可精修原子模型","未执行最终复核、checkCIF 与交付"],"confidence":"low"}`。
>    但 `verdict.json` / `state.json.agent_text` 记的却是主回合最后那句等待语
>    （`{"unparsed": "状态无变化：原求解仍在运行，没有新节点或错误。继续等待。"}`），
>    收尾回合的 SSE 没进 `sse.jsonl`（该文件止于 seq 2961 = 主回合 `turn_completed`）。
>    等级 no_delivery 无误（确实没有 final.cif），但**"诚实度"一栏该记这一格及格**。

---

## 1. 两格时间线

### 1.1 纯工具臂 org-tools-r1（15:55:19 起，120 min 全用完）

| 阶段 | 相对时刻 | 内容 | MCP 调用 / 失败 |
|---|---|---|---|
| A 探面 | 0.00–0.67 | 三次 `exec` 过滤 `ALL_TOOLS`，第三次逐个打印 11 个目标工具的 description+schema（含 `run_shelxt`、`solve_charge_flipping`） | 0 / 0 |
| B 摄入 | 0.67–0.98 | `get_project_brief` → `ingest_vendor_data(list_candidates)` → `ingest_vendor_data(hkl=crystal.hkl, ins=start.ins)` | 3 / 0 |
| C 筛群 | 1.30–1.89 | `screen_space_groups(laue_group="mmm", merge_stats)`、`reflection_statistics(laue_group="all")`、`get_project_brief`、`change_space_group("P m m m")` | 5 / 0 |
| D 求解试探 | 2.10–3.29 | `run_shelxt`（**0.008 s 失败**）→ `solve_superflip`(Pmmm, 1.6 s 失败) → `change_space_group("P -1")` → `solve_superflip`(5.9 s 失败) → `change_space_group("P m m m")` → **`solve_charge_flipping`** 发出 | 7 / 3 |
| E 等电荷翻转 | 3.29–68.30 | **65.0 min**：76 次 `wait`(cell 18，yield 30 s→50 s→55 s 三级加长)、50 条等待语。3 900 s 时 codex 报 `timed out awaiting tools/call after 3900s` | 1 / 1 |
| F 改走 SHELXT | 68.62–98.79 | `run_shelxt(composition="C", detach=true, timeout_s=900)`；38 次 `wait`(cell 19)、29 条等待语；**1 810 s 后返回 `gave up waiting … 'solve_charge_flipping' (running 5729s so far)`** | 1 / 1 |
| G 监测项目锁 | 98.95–129.05 | `get_project_brief` 排队；22 次 `wait`(cell 20)、22 条等待语；**1 805 s 后 `gave up waiting … (running 7545s so far)`**（该返回落在 18:04:47，比案例结束晚 9 min） | 1 / 1 |
| H 收尾 | 17:55:45–53 | 主回合 interrupted 后的收尾回合，输出诚实裁决 | 0 / 0 |

**合计**：全部 15 次 MCP 调用中，**12 次发生在前 3.5 min**（3 次失败）；此后 116.5 min 只发出 3 次调用，全部失败，全部是"等/排队"。

### 1.2 全栈臂 org-full-r1（17:55:51 起，17.4 min）

| 阶段 | 相对时刻 | 内容 | MCP 调用 / 失败 |
|---|---|---|---|
| A 摄入+全类筛群 | 0.00–1.22 | 探面 → `get_project_brief` → `ingest_vendor_data` ×2 → `set_experiment()` + **`read_skill(data-ingest-space-group-protocol)`** → **`screen_space_groups(laue_group="all", merge_stats=true, max_out=50)`** → `reflection_statistics(n_shells=12)` + `estimate_resolution` + **`audit_reflection_data`** → `situation_report` → `change_space_group("P m m m")` | 13 / 0 |
| B Pmmm 试解 | 1.45–3.67 | **`run_shelxt(composition="C H N O", …)` 7.2 s 成功**（Pmmm，R1 0.53，C51 N20，30 原子）→ `view_structure`(asu 四视角)+`view_structure`(cell) → `inspect_model` → `refine(iso)` → `solve_charge_flipping(seeds=[0,1,2,3], max_attempts_per_seed=5)` **69.5 s 失败** | 5 / 1 |
| C 证据探针 | 3.90–6.82 | `probe_site`(C008 近旁试 O/S/Cl/Br，22.7 s) → `ghost_test`(12 个原子，27.9 s) → **`read_skill(framework-solve-ladder)`** → `solve_superflip` 60.3 s 失败 | 4 / 1 |
| D 降群求解+对称回收 | 7.02–9.09 | `branch`×2 → `change_space_group("P -1")` → **`run_shelxt(composition="C H N O", space_group="P -1")` 2.6 s，得 R1 0.072 的 P1 解（52 原子）** → `refine` → `check_symmetry`+`ncs_audit`（此时**无额外算符**，只有 fraction 0.885 的近失配，6 个不匹配原子全是元素标错的那几个）→ `inspect_model`×2 → **`edit_atoms(reassign N00F→O, N00M→C, O00E→N, C00T→N)`** → `refine` → **`check_symmetry` 三个算符 fraction 1.0 → suggested "P 21 21 21"** → `branch`×2 → **`change_space_group(adopt_suggestion=true)`：52 原子并成 13，completeness 0.494→1.0，Rint 不变 0.0117** | 16 / 0 |
| E P2₁2₁2₁ 精修 | 9.24–11.94 | `refine(iso)` → `add_hydrogens(C)` → `refine(aniso)` → 与 P1 各向异性节点 `compare_nodes`（P2₁2₁2₁ R1 0.0356 / 117 参数 vs P1 0.0395 / 468 参数）→ `checkout` → `add_hydrogens(C,N)` → `refine` → `audit_element_assignment`+`validate_structure` → `assemble_asu(dry_run)`+`assemble_asu` → `rename_atoms(canonical)` → `situation_report(render)` → `refine` → `compare_nodes` | 20 / 0 |
| F 复核+换手 | 12.15–13.93 | `run_shelxl(adopt_wght)` → **Flack 1.007(8)** → **`read_skill(flack-absolute-structure)`** → `invert_structure` → `run_shelxl(adopt_wght)` → **Flack −0.007(8)**，R1 0.0264 → `run_shelxl(adopt)` R1 0.0263 → `view_structure(supercell)` → `get_geometry`+`validate_structure`（0 警报）→ `run_shelxl(check, l_s=0)`+`run_shelxl(check, l_s=15)` | 10 / 0 |
| G 交付 | 14.16–16.64 | **`write_outputs`（14.16 min，status=provisional）** → `run_checkcif`(15.2 s) → `branch`+`change_space_group("P 21 21 21")`（15.18 min，见 §4.4）→ `checkout(n0064)` → shell patch 写 SUMMARY.md/VALIDATION.md → `finalize_delivery` **被拒**（6 条 A 警报）→ `finalize_delivery(waivers=…)` 成功 | 7 / 1 |

---

## 2. 分岔点逐一对照

### 2.1 筛群：一个劳厄类 vs 全部劳厄类（1.3–1.5 min，第一处实质分岔）

- 纯工具臂 1.30 min：`screen_space_groups(laue_group="mmm", max_out=20, merge_stats=true)`，
  只筛 mmm 一个类。1.49 min `reflection_statistics(laue_group="all", n_shells=10)` 返回的
  `laue_scan` **只有每类 R_int**（`[{P m m m, r_int 0.0117}, {P 1 2/m 1, 0.0}, …]`），
  `e_statistics` 只有一份，mmm 合并下的 `mean_abs_e2_minus_1 = 0.957, hint "centrosymmetric"`
  （参考值：中心 0.968 / 非心 0.736）。`friedel = null`，`wilson = {"skipped": "no model/composition
  in the session"}`。它据此在 2.09 min 写下：「Laue 一致性（R_int 0.0117）、近完整度 98.2% 与
  **强烈中心对称统计**共同支持正交中心对称起点」。
- 全栈臂 0.64 min：`screen_space_groups(laue_group="all", merge_stats=true, max_out=50)`
  ，正是 v32 模板的硬规则原文："**劳厄类拿不准时 laue_group='all' + merge_stats=true 一次给
  所有类的 Rint 与候选表**，不要逐类调用，更不要用 change_space_group 逐群声明来"看 Rint""。
  这一路返回的 `laue_scan` **每类都带自己的 E 统计**：
  `P m m m → 0.957 hint "centrosymmetric"`；**`P 1 2/m 1 → 0.806 hint "non_centrosymmetric"`**。
  0.75 min 它又调了 `audit_reflection_data`（纯工具臂全程没调过），拿到
  `e_statistics.mean_abs_e2_minus_1 = 0.781` 与那段处方式说明：
  "reads acentric-or-flatter … **Settle centro-vs-acentro by trial: solve/refine in the
  CENTROSYMMETRIC candidate first (Marsh discipline) and only keep the acentric group if the
  centric one demonstrably fails; after any P1 solve, run check_symmetry**"，以及
  `twin_alarm.signs = ["metric_exceeds_laue"]`。
- **判读**：同一份数据，纯工具臂手里只有一个"中心对称"的数字，全栈臂手里有"0.957 中心 /
  0.81–0.78 非心"的矛盾对与"先中心后非心、P1 解完跑 check_symmetry"的处方。这条差异**不是模型
  能力差异，是调用面差异**，而调用面是模板规则直接指定的。

### 2.2 "P m m m" 占位声明（两臂完全相同）

两臂都把中心对称劳厄类当占位群显式声明：纯工具臂 1.89 min、全栈臂 1.22 min，
`change_space_group("P m m m")` 都返回同一段
`"mode": "atomless_declaration" … "verdict": "no_absence_conditions"`。纯工具臂原话
（2.09 min）：「已显式声明 Pmmm，并将让 SHELXT 在该 Laue 类内独立检验和求解」。
**这一步两臂无差别，不是分岔点。**

### 2.3 `run_shelxt` 的元素清单错误：一句错误消息决定了两个小时

纯工具臂 2.10 min：
`run_shelxt({adopt:true, all_space_groups:true, chem_quality:true, n_phase_sets:100, timeout_s:600})`
→ **0.008 s 返回** `{"ok": false, "error": "no element list available - pass composition='C H N ...'"}`。

它看到的工具说明（0.46 min 自己打印过）是：
"Solve the structure ab initio with the real SHELXT … **Needs only the cell + element list, no
starting atoms.** Writes a TREF job from the session cell/SFAC …"，
schema 是 `{ adopt?; all_space_groups?; chem_quality?; composition?: string; detach?; from_job?;
job_status?; n_phase_sets?; …}` - **`composition` 有名字，没有一行注释**（同一份 dump 里
`change_space_group` 的每个参数都有注释）。

它的反应（2.49 min，agent 原话）：

> 「**数据未提供元素清单，SHELXT 因而不能启动。**我会先用不依赖化学组成的 Superflip 获取独立
> 电子密度峰，再依据峰强、几何与精修残差谨慎判定元素；无法由 X 射线唯一确定的身份会明确保留为
> 不确定。」

推理侧的证据（3.15 min）：

> "There could be a superflip failure due to chemistry … I think using the built-in
> solve_charge_flipping could be better for this. I need to ensure the description is correct,
> especially since **it doesn't require explicit composition** for max_peaks."

**它为什么不按提示补 `composition=` 重试**：三条可核证的原因：

1. 它**把错误读成数据缺陷而不是参数缺省**（「数据未提供元素清单」）。错误文本给的是参数名，
   没有说"猜一个通用轻原子串是合法搜索参数"。
2. 它的 AGENTS.md（纯工具版）里唯一相关的规则是诚实守则："**不编造实验元数据与结构：不知道
   就说不知道，交给用户补充。**" 在没有任何"占位组成串只是峰高启发"的对冲说明时，凭空写一个
   化学式看起来正是这条禁令要禁的事。`TEMPLATE_TOOLS_ONLY` 全文 grep：`composition` 0 次、
   `SFAC` 0 次、`shelxt` 0 次。
3. 会话里**看不到 SFAC**。`start.ins` 明明有 `SFAC C H N O`，但
   `ingest_vendor_data` 的 `candidate_table` 只报 cell/wavelength/`space_group_guess`；
   `get_project_brief` 的 `model.element_counts = {}`；`reflection_statistics` 的 Wilson 块直接
   `"skipped": "no model/composition in the session"`。它在 1.48 min 其实想到过这件事：
   "I'm wondering if **start.ins includes SFAC**, maybe there's a tool imported or information in
   the project brief." ——查了 project brief（1.67 min）没有，**然后就放弃了**。它全程 20 次
   `exec` 没有一次是 shell/python（全是 `ALL_TOOLS` 过滤或 MCP 包装），**从未去读 start.ins**，
   尽管它的契约明确允许分析性读取（"分析性脚本可用引擎解释器 … 只用于读与算"）。

全栈臂在**第一次**调用就带上了组成（1.45 min）：
`run_shelxt({composition:"C H N O", space_group:"P m m m", all_space_groups:true,
solve_resolution:0.805, timeout_s:300, adopt:true})` → **7.2 s 成功**。
调用前的推理（0.98 min）：

> "**Determining composition details**: I'm considering using SHELXT for the composition,
> perhaps starting with a **default SFAC** since I need to figure out if the tool accepts optional
> compositions. I'll look into running SHELXT after declaring Pmmm with a **generic 'C H O'
> composition**, as it could solve an organic structure. **The cell volume is around 881 Å³**,
> suggesting it might be a small molecule."

**它是从哪儿知道"通用占位组成串"这件事的？**逐一核对：

- **它读的那张卡里没有**。0.56 min 读的 `data-ingest-space-group-protocol`
  （`knowledge/skills/data-ingest-space-group-protocol.md`）全文 grep `composition` → 只有一处
  第 94 行"ASU 原子数×Z 与**组成先验**对不上"，与 SHELXT 传参无关；SHELXT 的 `composition`
  在这张卡里**一次都没出现**。
- **v32 模板里有，而且是字面量**。`crystalpilot/workbench/agents_md.py` 第 368 行（TEMPLATE 内）：
  "**SHELXT 组成串（尤其占位的 C H N O）给出的 C/N 标签只是峰高启发，不是元素证据**"；
  第 181 行的 run_shelxt 条目又把 composition 列为搜索旋钮：
  "说 best CFOM 低于录取线则改搜索（solve_resolution/**composition**/chem_quality/space_group=）
  不改预算"。也就是说，**模板既给了那个字符串，又把它定义成"搜索参数"而非"化学主张"**，
  正好解掉纯工具臂的第 1、2 条障碍。
- 工具 description 两臂相同（"Needs only the cell + element list"），所以**"参数存在"这件事
  两臂都知道**；差的是"允许猜、猜了不算撒谎"。

> **这是本泳道最干净的一处知识层因果**：同一条错误消息，纯工具臂读成"数据不足→换引擎"，
> 全栈臂在还没撞上错误之前就按模板的字面提示传了 `composition="C H N O"`。

### 2.4 Superflip 与 P −1 弯路：同一个弯路，两种用法

纯工具臂：

- 2.52 min `solve_superflip({d_min:null, max_peaks:60, maxcycles:1000, randomseed:20260903,
  timeout_s:600})` → 1.6 s 失败，`final_r_percent 35.8`，
  `symmetry_agreement {per_operator: [], overall: 49.62}`。
- 2.72 min `change_space_group("P -1")` → 3.02 min `solve_superflip({allow_low_completeness:true,
  maxcycles:5000, max_peaks:80, …})` → 5.9 s 失败，`final_r_percent 70.3`，
  **`per_operator: [{op_number 2, symbol "-1", agreement 70.74}]`**，工具自带判词：
  "<~0.25 = operator confirmed in the density; **large values mean the density does NOT obey that
  operator - an independent space-group alarm**"。
- 3.15 min **`change_space_group("P m m m")` 退回中心对称群**，3.29 min 在这里发出电荷翻转。

也就是说：**工具已经用密度空间的独立判据告诉它"反演心不成立"（70.74 ≫ 0.25），它 8 秒后
把群改回了中心对称的 Pmmm**。它的推理（3.15 min）完全没有提到 symmetry_agreement，
只说 "whether the data might be merged in mmm, and if the solution group is Pmmm"。
**这是纯工具臂唯一一次拿到手却没用的关键证据。**

全栈臂：

- 6.82 min `solve_superflip({d_min:null, max_peaks:60, randomseed:12345, timeout_s:180})`
  → 60.3 s 失败（`overall 63.05`，`per_operator: []`）。
- 7.15 min `change_space_group("P -1")` - **它用 P −1 换的不是引擎参数，是引擎的搜索范围**：
  `run_shelxt` 的 description（两臂都读过）写着 "SHELXT determines the group **WITHIN the Laue
  class implied by the job's LATT/SYMM**"。声明 P −1 → SHELXT 只在三斜类里找 → 7.29 min
  返回 **R1 0.072 的 P1 解（52 原子）**，一步跳出中心对称正交的死胡同。
- 之后是 §4.3 的对称回收链。

**同一个 P −1 弯路：纯工具臂用它重跑同一个失败引擎（6 s 后放弃），全栈臂用它改变搜索空间。**
两臂手里的事实（SHELXT 受 LATT 限制）完全相同，差别是全栈臂在第 7 分钟还活着、还在迭代，
而纯工具臂在第 3.3 分钟已经把整格时间押上了。

### 2.5 `solve_charge_flipping`：那一次调用的参数、schema 说了什么、有没有警告

纯工具臂 3.29 min（Pmmm，中心对称占位群，无原子会话）：

```
solve_charge_flipping({ d_min: 0.9,
                        seeds: [101,203,307,409,503,607,709,811],   // 8 个
                        max_attempts_per_seed: 20,
                        max_solving_iterations: 5000,
                        max_peaks: 80 })
```

全栈臂 2.51 min（Pmmm，已有 SHELXT 30 原子模型）：

```
solve_charge_flipping({ d_min: 0.805, seeds: [0,1,2,3],
                        max_attempts_per_seed: 5,
                        max_solving_iterations: 5000, max_peaks: 60 })
→ 69.5 s 返回 "charge flipping: no phase transition"
```

**工具的 description/schema 说了什么**（两臂 dump 出的文本逐字相同）：

> "Solve the structure ab initio by charge flipping in the current working space group. …
> **Key knobs: resolution truncation (d_min), random seeds, iteration budget. Typical d_min
> 0.9-1.1 for MOFs; try more seeds or different d_min on failure.**"
>
> schema：`allow_low_completeness?`（有注释）、`d_min?`（有注释）、`delta?`（有注释）、
> **`max_attempts_per_seed?`（无注释）**、`max_peaks?`（有注释）、
> **`max_solving_iterations?`（无注释）**、`seeds?`（有注释 "random seeds tried until phase
> transition"）。**没有 `timeout_s`，没有 `detach`，没有任何预算量级、单次尝试代价、上限说明。**

对照源码 `crystalpilot/tools/solution_tools.py`：默认 `max_solving_iterations=400`、
`max_attempts_per_seed=2`、`seeds=[1,2,3,4]`；`run()` 里是裸的
`for seed in seeds: … charge_flipping.loop(it, …)`，**全程没有任何墙钟检查**。
纯工具臂那组参数 = 8×20 = 160 次尝试（默认 8 次的 **20 倍**）× 每次 5 000 次求解迭代
（默认 400 的 **12.5 倍**）。schema 里没有一个字告诉它这意味着什么。

**有没有工具输出警告过它？**

- **预算上：一次都没有。** 唯一的反向忠告写在**失败返回**的 `hint` 里：
  "one d_min variation (0.8-1.2) is a legitimate retry; beyond that, **blind d_min/seed scans have
  a poor record (r13: 3 runs, 10 min, zero yield)** - prefer escalating the ladder: run_shelxt …"。
  全栈臂 3.67 min 收到了这条（并照办：转 superflip、再降群）；**纯工具臂的调用根本没返回过，
  所以永远收不到这条 hint**。一条只在成功返回时才送达的忠告，对"卡住"这个失败模式无效。
- 更糟的是 description 的最后一句 "**try more seeds** or different d_min on failure" 和
  `d_min 0.9-1.1` 的建议**正好把它推进那组致命参数**：它上一次刚被 superflip 失败，
  按 description 的字面建议加种子、取 d_min 0.9。
- 另有一条误导：低完整度守卫的文案（`solution_tools.py:62, 68`）写 "**keep timeout_s SHORT**" /
  "keep the timeout short"——而这个工具**没有 `timeout_s` 参数**（有的是 `solve_superflip`）。
- 群方向上也没有提示：中心对称占位群里跑电荷翻转求非心结构，工具不做任何提醒。

### 2.6 那 65 分钟：等待语、计数、以及它有没有想过别的路

从 3.29 min 发出调用到 68.30 min 收到 codex 超时，**65.0 min**：
`wait(cell_id=18)` **76 次**（`yield_time_ms` 自己从 30 000 → 50 000 → 55 000 三级加长），
配 **50 条**等待语（全程共 108 条 agent 消息，其中 E/F/G 三段等待共 **101 条**：50+29+22）。
四条原话：

> 6.39 min：「电荷翻转仍在多种子搜索中，工具持续运行且未报错；我会等待它完成，**不会中止或
> 旁路重跑**。」
>
> 14.27 min：「该调用已进入较长的后续随机种子批次，但仍有心跳。**按工作台契约我不会杀进程**；
> 继续等待完成结果。」
>
> 26.42 min：「当前搜索仍未终止且没有报错；**由于中止会丢失全部相位搜索进度**，我继续等待
> 自然完成。」
>
> 46.64 min：「计算仍在执行。**未并发启动其他模型修改，避免排队和状态冲突。**」

**它考虑过替代方案吗，考虑过三种，全部被自己的契约否掉：**

1. **中止/换路**：反复被"绝不杀进程"挡住。契约原文（两臂都有）："长时间计算有心跳进度，
   **慢≠卡死**；绝不杀子进程、绝不绕开工具直跑，重跑 = 再次调用同名工具。"
2. **并发/第二条线**（另起分支或第二个项目）：被串行规则挡住。契约原文："同一项目的工具调用
   **串行执行**：并发只省回合不省时间"。它 46.64 min 的原话就是这条规则的复述。
   **注意：它从未想到"另开一个项目/会话"这一层**: rollout 里没有任何 branch/新项目/
   小预算重调的念头，全部 20 条推理里没有一处提到降低 seeds/attempts 重试。
3. **"是不是在等审批"**：这是它唯一自发的诊断假设，出现 5 次
   （35.61、70.78、77.27、86.83、95.43 min）。35.61 min 推理原话：
   "I'm wondering if the nested tool might be blocked due to approval issues. **The contract
   mentions that non-auto shell and edit tools may need approval**, but I'm thinking this isn't
   the solution. It seems the user may have missed some approval process? I can't know for sure."
   ，契约里那句"非 auto/full 档位下…表现为调用迟迟不返回；**照常等待**"把这个假设也导向继续等。
   **事实：整份 rollout 里没有任何审批事件**（`approval` 类记录 0 条），没有任何东西在等审批。

它也自己算过预算（44.58 min）："if I'm looking at 160 times 5000 iterations, using FFT might
only take about an hour. I should probably let it run and wait"——**估出了"约一小时"这个正确
量级，然后选择等**。49.79 min："I've been at this for about 40 minutes, and I think I can manage
for another 2 hours. However, I'm wondering if there might be a **potential deadlock** with the
project? **It's specified in the contract that we should never kill the process.**"

它还发现了工具面的一个真缺口（20.28 min）："I'm thinking about the 'heartbeats' function and
**why it waits without showing the nested tool progress**"，以及 56.05 min："if I were to use
nested tools, it seems **notifications might not forward properly**"。，MCP 侧确有 20 s 心跳，
但经 `exec`+`wait` 这条路**送不到模型上下文**，所以它 136 次 `wait` 全是盲等。

### 2.7 codex 3 900 s 超时之后

- **68.30 min**（约 17:03）：`solve_charge_flipping` 以传输层错误结束：
  `tool call error: … Caused by: timed out awaiting tools/call after 3900s`。
- **68.61 min** agent 消息：「这次多种子电荷翻转在工作台 3900 秒硬超时前未返回，且未提交模型。
  下一步改用 SHELXT；**因无化学式，我只提供"C"作为中性通用轻原子散射占位**，不把它当作元素
  结论，后续将依据密度、键长和 ADP 逐位审计。」，**被逼到墙角时它自己发明了占位组成串**，
  只不过用的是最贫乏的 `"C"`（全栈臂 66 分钟前用的是 `"C H N O"`）。
- **68.62 min**：`run_shelxt({composition:"C", adopt:true, all_space_groups:true,
  chem_quality:false, n_phase_sets:50, timeout_s:900, detach:true})` - detach 用法正确。
- 但它**从未返回作业号**：38 次 `wait` + 29 条等待语之后，**98.79 min** 返回
  `gave up waiting after 1810s: 'solve_charge_flipping' (running 5729s so far) is still executing.
  Calls on one project run one at a time; re-issue this call after it returns - do NOT kill
  processes, nothing was interrupted.`
- **98.95 min** agent 自己把根因说对了（本泳道最漂亮的一句自诊断）：
  「**已确认根因：不是 SHELXT 本身卡住，而是前一条电荷翻转虽在客户端 3900 秒超时，服务器端仍
  持续运行，后续调用按项目串行规则排队并在 1810 秒后放弃等待；没有进程被中止。**现在只监测
  项目锁，等原求解自然结束后再继续。」
- 随后 `get_project_brief` 也排进同一把锁，22 次 `wait` 后于 **129.05 min（18:04:47，
  比案例超时晚 9 min）**返回 `gave up waiting after 1805s: 'solve_charge_flipping'
  (running 7545s so far)`。
- **17:55:43** 主回合被案例超时 `interrupted`（`duration_ms 7212300`）；收尾回合给出诚实裁决。

**平台事实（可核证，非推断）**：客户端放弃 ≠ 服务端停算。电荷翻转在服务端至少跑到 **7 545 s
（2.1 h）**，项目锁一直被它持有；`QUEUE_MAX_S = 1800.0`（`crystalpilot/mcp/server.py:46`，
放弃文案在 :109-111）意味着**此后每一次调用都要先烧掉 30 min 才拿到一句"我没等到"**。
纯工具臂 116.5 min 里只发出 3 次调用、全部如此收场，就是这个机制的直接后果。

---

## 3. 纯工具臂自己想出了什么（对与错）

**对的、且是它自己想的：**

1. **把"没有消光反射"当成信号读了出来**（1.48 min 推理）："I'm noticing that there are **no
   absent observations due to the data merge** … It mentions 'no absent obs', so the file likely
   already combined and **omitted any that were absent**." ——它正确识别出这是"消光已被剔除的
   合并数据"，而工具给它的只是逐群一句 `no_absence_conditions`。这一步的判断力**超过了工具的
   表达力**。
2. **怀疑过 SFAC**（1.48 min，见 §2.3），方向完全正确，只差一步 shell 读文件。
3. **知道 Laue 度规 ≠ 真对称**：1.29 min 消息「`start.ins` 的 P1 只是**未验证占位**。现在以
   消光、Laue 合并和强度统计共同判定候选空间群」；2.09 min 明确把 Pmmm 说成"让 SHELXT 在该
   Laue 类内独立检验和求解"的占位声明，**没有把它当结论**。
4. **求解成功也不等于采纳**（8.35 min）：「完成后我会先查看密度峰是否组成合理化学骨架，
   再决定是否接受该空间群，**而不会仅凭算法"收敛"就采纳**。」这句话等价于 v32 模板的
   "化学合理性 > R 值"，**它自己说出来了**。
5. **给失败留证据价值**（12.31 / 16.32 min）：「若最终无相变，将根据其失败证据切换到明确记录的
   候选空间群试验，而不是重复同一路径」「若峰图不支持 Pmmm，我会**保留这次失败作为空间群
   反证**」。
6. **自诊断出平台缺陷**（98.95 min，见 §2.7），比现场笔记的结论早了约 10 分钟，且完全正确。
7. **诚实到底**：收尾裁决 `solved:false / n_atoms:0 / confidence:"low"` + 4 条 unresolved，
   **没有编任何结构或指标**。`analyse_case` 的 `leakage=[]`、`path_token_cited=false`，
   它也没有去偷看 staging 里的参考信息。

**错的（判断层面，非工具层面）：**

1. **E 统计单点锚定**：只拿到 mmm 合并的 `0.957 → centrosymmetric` 就写"强烈中心对称统计"，
   而 P2₁2₁2₁ 的真值应在 0.736 附近。它没做交叉：没调 `audit_reflection_data`、
   没用 `screen_space_groups(laue_group='all')` 看别的类。**注意这半个错要记到工具账上**：
   逐类 E 统计只在 `screen_space_groups(all)` 里，`reflection_statistics(all)` 的 `laue_scan`
   只给 R_int（§2.1）。
2. **无视 superflip 的密度空间判据**：P −1 下 `-1` 算符 agreement 70.74（判词写明"密度不服从
   该算符"），它 8 s 后把群改回了中心对称 Pmmm（§2.4）。
3. **一次调用押上全格**：160×5000 的预算发在**错群+无原子**的会话上，且此后不再有 B 计划。
4. **把参数缺省读成数据缺陷**（§2.3）。

**它做了哪些全栈臂的规则明令禁止的事？**

- **求解预算纪律**：v32 模板对 SHELXT 写着"n_phase_sets … **>500 钳到 500，绝不加大**"、
  "**大胞不要阻塞等**：detach + job_status 轮询"、"best CFOM 低于录取线则**改搜索不改预算**"。
  纯工具臂 2.10 min 传 `n_phase_sets:100`（未越界但方向相反），3.29 min 的电荷翻转 8×20×5000
  正是"改预算不改搜索"的教科书反面。**但必须说清：这几条纪律模板只写给 SHELXT，
  `solve_charge_flipping` 连在 v32 里也没有预算上限条款**：全栈臂之所以没踩，靠的是
  `seeds=[0,1,2,3], attempts=5` 这种保守习惯 + 失败返回里的 hint，**不是靠一条硬规则**。
- **静默改群**：两臂的诚实守则都写"空间群不做静默改判"。纯工具臂三次 `change_space_group`
  全部走了显式工具、全部有返回记录，**未发现违规**。
- **绕开工具直驱引擎 / 杀进程 / 碰原始数据 / 读密钥**：**未发现**（`shell_hazards=[]`、
  非 MCP 的 shell 调用 0 次、`leak_clean=true`）。它对操作契约的遵守是**过度**的，不是不足。

---

## 4. 全栈臂靠了哪些卡 / 规则

### 4.1 三次 `read_skill`，全部在动手前、全部读整卡（未用 `section=`）

| 时刻 | 卡 | 紧接着的动作 | 卡里真正起作用的内容 |
|---|---|---|---|
| 0.56 min | `data-ingest-space-group-protocol` | `screen_space_groups(laue_group="all")` → `audit_reflection_data` | "定群依据 = 消光筛表 + E 统计（\|E²−1\|≈0.97 中心 / ≈0.74 非心）"；"筛表是三态的：**undecidable 不是支持**"；"螺旋/滑移 undecidable 只警告，按 **Marsh 纪律**以求解试错定夺"。**注意：这张卡不含 `composition`**（§2.3） |
| 5.71 min | `framework-solve-ladder` | `solve_superflip` → 降群到 P −1 用 SHELXT | "SHELXT … **P1 相位回推 Laue 群内所有群**"；"**自认边界：不适合严重无序与孪晶**"；"电荷翻转要求高完整度"；"best CFOM 在 0.65 之下：**改搜索而不是改预算**（solve_resolution 砍噪音壳、**composition 如实申报**、chem_quality、space_group=）" |
| 12.27 min | `flack-absolute-structure` | `invert_structure` | 四分支表第 ② 行："≈1 → 模型是对映异构体 → `invert_structure` → 重跑 run_shelxl 确认归零，翻转前后对照即竞争精修"；"优先 Parsons 商法"；"su>0.3 基本无判定力" |

### 4.2 可见地驱动了行为的模板规则（逐条给出被执行的动作）

1. **筛群口径**（模板 §工具图谱 screen_space_groups）："**劳厄类拿不准时 laue_group='all' +
   merge_stats=true 一次给所有类的 Rint 与候选表**，不要逐类调用" → 0.64 min 的调用**逐字照做**
   （`laue_group="all", merge_stats=true, max_out=50`），也正是它拿到"非心 0.806"那一行的原因。
2. **SHELXT 组成串**（模板第 368 行）："**SHELXT 组成串（尤其占位的 C H N O）给出的 C/N 标签
   只是峰高启发，不是元素证据**" → 1.45 min `composition:"C H N O"`；且 3.87 / 4.95 min 的推理
   正是这条规则的应用："why SHELXT overfits … it automatically maxes out the atoms based on
   composition"、"SHELXT outputs the formula C51 N20 based on **peaks** rather than the inputted
   data. N (Z7) is assigned as the strongest component, while C (Z6) takes the rest"
   ，**它没有把 SHELXT 的 C51 N20 当成化学**。
3. **亲眼看结构**（模板 §判断方式）："`view_structure` **亲眼看结构**（ASU 之外还要看堆积，
   单一视角单一状态会误导）" → 1.81 / 1.93 min（asu 四视角 + cell 四视角）、13.10 min
   （supercell a/b/c）。13.25 min 推理："the packing images … seem physically distinct with
   **no overlaps**"。
4. **branch 是你自己的活**（模板 change_space_group 固定链路 "branch → change → refine →
   add_hydrogens → 重精修 → compare_nodes"）→ 7.02、9.07、10.05、14.87 min 共 7 次 `branch`；
   10.39 min 与 11.94 min 两次 `compare_nodes`，其中 10.39 min 是**同等条件下的群竞争**
   （P2₁2₁2₁ R1 0.0356 / 117 参数 vs P1 0.0395 / 468 参数，`delta_b_minus_a.r1_strong = −0.0039`）。
5. **ASU 连贯性**（专家铁律）："交付前每个片段必须与主片段直接成键（assemble_asu）" →
   11.06 min `validate_structure` 报 `asu_detached`（10 个片段经对称像）→ 11.21 min
   `assemble_asu(dry_run)` + `assemble_asu` → 13.25 min `validate_structure` **0 警报**。
6. **标签必须能读成其元素**（write_outputs 条款）→ 11.33 min `rename_atoms(mode="canonical")`，
   交付 CIF 的标签是 C1–C8 / N1 / O1–O4。
7. **交付链路固定** → 13.49 + 13.74 min `run_shelxl(check)` → 14.16 min `write_outputs` →
   14.61 min `run_checkcif(final.cif)` → shell 写 VALIDATION.md / SUMMARY.md → `finalize_delivery`。
8. **诚实守则**"不编造实验元数据" → 14.34 min 推理抓到 SHELXL 的占位温度：
   "there's a temperature of 293(2) mentioned, but it comes with a caveat about an unknown status …
   **This raises some honesty issues**"，最终两条 unresolved 都是"输入未提供的实验元数据"。

### 4.3 它自己的关键判断：用元素一致性把对称性解锁（7.85 → 9.09 min）

这一段没有任何卡在指路，值得单列：

- 7.85 min `check_symmetry`（P1，52 原子）：**没有额外算符**，只有一条 fraction 0.885 的近失配
  `-x,y,-z`，`unmatched` 恰好列出 6 个原子 `[O006 2.26, O00E 2.24, N00F 3.48, N00M 3.22,
  C00S 1.5, C00T 1.34]`，全是 SHELXT 按峰高乱指的 C/N/O。
- 8.30 min 推理：它按几何把四个 P1 拷贝配对："I'm looking at the chemical formula **C8N1O4**
  and noticing some inconsistencies between the fragment counts … **Fragment 4 matches what I
  expect**, but fragments 1, 2, and 3 show discrepancies in carbon and nitrogen counts. I need to
  **pair and map the atoms according to their geometry and bonds**"；并读出化学：
  "It seems like a **5-member ring might form a lactone structure, with the nitrogen outside**"。
- 8.60 min：逐对定元素 "O006 ↔ N00F … **N00F should correspond with O**"。
- 8.62 min `edit_atoms(reassign: N00F→O, N00M→C, O00E→N, C00T→N)` → 8.77 min `refine`。
- 8.86 min `check_symmetry`：**三个算符全部 fraction 1.0**
  （`x+1/2,-y+1/2,-z+1/2` / `-x,-y,z+1/2` / `-x+1/2,y+1/2,-z`，mean_dev 0.033–0.049 Å），
  `suggested_space_group = "P 21 21 21"`。
- 9.09 min `change_space_group(adopt_suggestion=true)`：52 → 13 原子
  （`n_p1_copies_merged: 39`），completeness 0.494 → **1.000**，Rint **不变** 0.0117
  （工具自带的回滚判据 "a large jump means the DATA do not share the model's pseudo-symmetry"
  正好通过）。

**在这条数据上（消光缺失、E 统计误导中心对称），"P1 求解 → 元素自洽 → 模型算符审计 → 升群"
是唯一走得通的定群路线，而 agent 是自己拼出来的**（`audit_reflection_data` 的说明给了
"after any P1 solve, run check_symmetry" 这半句方向）。

### 4.4 Flack 与最终群：交付为什么发生在群"再声明"之前

- **群其实早在 9.09 min 就定了**（`change_space_group(adopt_suggestion=true)` →
  `P 21 21 21 (a+1/4,b,c-1/4)`）。"P2₁2₁2₁ 在 15.7 min 才出现"是对日志的误读。
- **Flack 链**：12.15 min `run_shelxl(adopt_wght)` → `flack 1.007, flack_su 0.08,
  flack_method "parsons"`，工具判词 "indicates the inverted structure - run invert_structure" →
  12.27 min 读 `flack-absolute-structure` 卡 → 12.54 min `invert_structure`
  （`operation "-x-1/2,-y,-z+1/2"`, `group_changed: false`）→ 12.74 min `run_shelxl` →
  **`flack -0.007, su 0.08` "consistent with the correct absolute structure"**，R1 0.0264→0.0263。
  判定力检查合规（su 0.08 ≪ 0.3，Cu 靶轻原子仍有信号，Parsons 656 商）。
  **注意：工具自己的 `flack_note` 已经说了 "run invert_structure"，卡在这一步是锦上添花而非
  必要条件。**
- **14.16 min `write_outputs`（status=provisional）**：交付发生在此，源节点 n0064，群已是
  P2₁2₁2₁。之后 14.61 min `run_checkcif` 报出 **A 122 "No _symmetry_space_group_name_H-M
  Given"**。
- **15.18 min 的 `change_space_group("P 21 21 21")` 是为了消掉这条 A 警报的补救尝试，不是定群**。
  它 15.40 min 的推理说得很清楚："the tool's P212121 symbol might include **origin transformation
  notation**, which the final CIF parser might ignore. I could use the change_space_group to the
  equivalent setting 'P 21 21 21', but that doesn't strip because it identifies the current
  basis." 调用返回证实了它的担心：`old → new` 都是 `P 21 21 21 (a+1/4,b,c-1/4)`，
  而且顺手把 11 个 H 剥掉了（`n_h_stripped: 11`，`dropped_metadata: ["h_riding_meta", …]`）。
  → **15.65 min `checkout(n0064)` 退回交付节点**，改为在 VALIDATION.md 里逐条解释并 waive。
- **交付 CIF 的群对不对？** `grade.json`：`reference_layer.sg_agent = "P 21 21 21 (a+1/4,b,c-1/4)"`,
  `sg_reference = "P 21 21 21"`, **`sg_type_equal: true`**；`emma.all_atoms` 13/13 匹配、
  **rms 0.001 Å、元素错配 0**；组成 C8H11NO4 / Z=4 与参考完全一致（`composition_max_rel_dev 0.0`）。
  **但 `self_consistency.cif.space_group = "?"` - CIF 里带对了对称算符 loop，
  `_symmetry_space_group_name_H-M` 字段是空的**，这就是被 waive 掉的 A 122。
  这是工具侧的写卡缺口，不是 agent 判断错误（见 §7.13）。

### 4.5 全栈臂的三次失败调用与错误文案

| 时刻 | 调用 | 返回 | 它怎么处理 |
|---|---|---|---|
| 3.67 min | `solve_charge_flipping(seeds=[0,1,2,3], attempts=5)` | `charge flipping: no phase transition`（69.5 s）+ hint "blind d_min/seed scans have a poor record… prefer escalating the ladder" | **照 hint 升阶梯**：先 probe_site/ghost_test 查证据，再 `read_skill(framework-solve-ladder)`，再换 superflip |
| 6.82 min | `solve_superflip(timeout_s=180)` | `superflip did not converge`（60.3 s，overall 63.05） | 转"降群让 SHELXT 换搜索空间" |
| 16.45 min | `finalize_delivery`（无 waivers） | `NOT finalized: … blocking (fix, or waive by id with a reason): alert:122_A … 183_A … 184_A … 185_A …` | 16.44 min 推理："**I should finalize the delivery first, possibly calling it without waivers to ensure I get the exact IDs**"——**把拒绝当成取 ID 的手段**，16.64 min 带 4 条逐项理由的 waivers 成功 |

---

## 5. 执行层

| 指标 | 纯工具臂 | 全栈臂 |
|---|---|---|
| 工具调用 / MCP / 失败 | 171 / 15 / 5 | 155 / 75 / 3 |
| 失败率（MCP） | **33 %**（5/15） | **4 %**（3/75） |
| 被失败消耗的墙钟 | **5 710 s**（3900 + 1810）＋ 1 806 s 排队 | 130 s（69.5 + 60.3） |
| `wait` 次数 | **136**（cell 18:76 / 19:38 / 20:22） | 8 |
| 等待类 agent 消息 | **101 / 108** | — |
| spin（同工具同参重复） | 2 组，各重复 1 次（`get_project_brief {}`、`change_space_group {"space_group":"P m m m"}`） | 5 组，各重复 1 次（brief / view_structure(cell) / check_symmetry / inspect_model(full) / add_hydrogens(C)） |
| arg_churn（同工具 ≥3 种参数） | **0** | **0** |
| error_chains | **0** | **0** |
| shell 危险动作 / staging 泄漏 / 路径 token 引用 | 无 / 无 / 无 | 无 / 无 / 无 |
| 非 MCP 的 shell 调用 | **0** | 1（用 `apply_patch` 写 SUMMARY.md / VALIDATION.md） |
| 审批事件 | **0**（但 agent 5 次假设"在等审批"） | 0 |

**误导性消息（两臂通用，本泳道实际造成损失的）：**

1. `run_shelxt`：`no element list available - pass composition='C H N ...'` - ins 里明明有
   `SFAC C H N O`；消息给了参数名却没给"允许猜"的许可（§2.3）。
2. `solve_charge_flipping` 的低完整度守卫文案叫人 "keep `timeout_s` SHORT"，**这个工具没有
   `timeout_s`**。
3. `screen_space_groups` / `change_space_group` 的 `no_absence_conditions` / "no absence
   conditions" **一词两义**：P 2 2 2、P m m m 是"本群没有消光条件"（真），
   P 21 21 21 是"本群有消光条件，但文件里那些类一条观测也没有"（消光被剔除了）。
   两者在返回里**字节级相同**（纯工具臂 1.30 min 的候选表；全栈臂 9.09 min 采纳 P2₁2₁2₁ 时
   的 `absence_audit` 也是同一句）。而**在 fcf 反推数据上，"该群消光类里 0 条观测"恰恰是螺旋轴
   存在的指纹**：工具把最强的正面证据说成了中性。
4. `friedel = null`，不说原因（文件已折叠 Friedel 对，所以非心的最直接证据这条路是封死的）。
5. `wilson = {"skipped": "no model/composition in the session"}`，缺 SFAC 的第二笔代价。
6. `run_shelxt` 在 P −1 下把候选解的群报成 `"Fp"`（全栈臂 7.29 min，`r1 0.072`），
   `"Fp"` 不是 Hermann–Mauguin 符号，实际采纳为 `P 1`。

**平台侧（本泳道最贵的一条，与臂无关）：**

- **客户端超时不取消服务端计算**。证据链：3 900 s 传输层超时（68.30 min）→
  `run_shelxt` 收到 `'solve_charge_flipping' (running 5729s so far) is still executing`
  （98.79 min）→ `get_project_brief` 收到 `(running 7545s so far)`（129.05 min，18:04:47，
  已在案例结束之后）。**服务端至少算到 2.1 h。**
- **项目锁 + `QUEUE_MAX_S = 1800`**（`crystalpilot/mcp/server.py:46`，文案 :109-111）：
  锁被一个无上限调用占住后，后续每次调用都要先烧 30 min 才拿到 "gave up waiting"。
  纯工具臂最后 60 min 就是两次 30 min 的空转。
- 错误文案本身是负责的（"do NOT kill processes, nothing was interrupted"），agent 也照做了；
  **问题不在 agent 的服从性，在于系统没有给它任何可执行的出路**：没有 cancel、没有"另起项目"
  的提示、没有把心跳送到模型上下文。

---

## 6. 一句话判读 + 不确定性

**一句话**：在这一格里，知识层的贡献不是"更强的晶体学直觉"，而是**三条把基座模型的直觉接到
工具上的接线**: (1) 许可它给 SHELXT 传一个占位组成串（模板字面量"占位的 C H N O"，
纯工具版 0 次提及），(2) 规定筛群要一次看全部劳厄类（因此拿到"非心 0.806"这条反证），
(3) 求解失败时"改搜索不改预算"的阶梯纪律；纯工具臂的晶体学判断力本身并不差（它自己识别出
消光被剔除、自己说出"化学合理性优先"、自己诊断出平台缺陷、最后诚实交白卷），**它是被一次没有
预算上限的工具调用锁死的**。

**哪些其实是工具层问题、换成全栈臂也可能中招：**

- **`solve_charge_flipping` 无墙钟上限 / 无 detach / 无 cancel**：v32 模板的求解预算纪律**只写给
  SHELXT**，对这个工具一个字都没有。全栈臂用 `seeds=[0,1,2,3], attempts=5` 纯属保守习惯，
  它 2.51 min 的推理里也没有任何"预算"字样。**同一组 8×20×5000 的参数由全栈臂发出，结果完全
  一样。**这是全泳道最该修的一条，且**修在工具层比修在模板层更可靠**。
- **错误文案措辞**（"no element list available"）：给了参数名、没给许可；换成"ins 声明了
  SFAC C H N O（UNIT 为占位），如确认化学请传 composition='C H N O'；占位串只影响峰高启发，
  不构成元素结论"，纯工具臂大概率当场就过了。这条**不需要任何晶体学知识层就能修好**。
- **SFAC 未暴露**：会话里没有任何工具肯说 ins 里的元素猜测，同一个缺口还顺手废掉了 Wilson 图。
- **消光缺失数据的表达**：`no_absence_conditions` 一词两义（§5.3），把螺旋轴的正面指纹说成中性。
  两臂都收到了同样中性的表格；全栈臂只是**另有一条 E 统计反证**才没被带偏。
- **逐类 E 统计藏在一个工具里**：`reflection_statistics(laue_group='all')` 的 `laue_scan` 不带
  E 统计，只有 `screen_space_groups(laue_group='all')` 带。纯工具臂调了前者、没调后者，
  于是"全部劳厄类"这个词给了它一个**名不副实**的全景。
- **心跳送不到模型**：136 次盲等，agent 两次自己指出这个缺口（20.28 / 56.05 min）。
- **审批状态不可见**：5 次错误假设"在等审批"，而实际审批事件为 0。

**反向的一句**：知识层也确实带来了成本与风险，全栈臂多花 2.3 M tokens（9.33 M vs 7.08 M），
且 `cache_write` 高一倍（721 k vs 257 k），代价来自每回合都要付的 26 KB 模板。这一格里它买到了
17 min 出发表级结构，值；但**这一格不能证明"规则压制推理"的反命题**：纯工具臂的推理没有被
压制过，它压根没机会展开。

**不确定 / 未能判定：**

1. **为什么纯工具臂那次电荷翻转跑了 ≥7 545 s，而全栈臂 20 次尝试只用 69.5 s？**
   尝试数只差 8 倍（160 vs 20），按线性外推应是 ~560 s。源码
   （`solution_tools.py:119-131`）显示 `max_attempts_per_seed` 传给
   `max_attempts_to_get_phase_transition`，`max_solving_iterations` 只限**相变之后**的求解迭代
   ，最可能的解释是纯工具臂某个种子**触发了（很可能是假的）相变**，随后进入 5 000 次求解迭代
   ＋ 80 峰搜索的昂贵分支，而全栈臂全程 `no phase transition` 走的是廉价分支。**但那次调用从未
   返回，日志里没有任何 summary 可以证实这一点**，只能存疑。
2. **`grade.json` 内部有一处自相矛盾**：`emma.all_atoms` 13/13 匹配、rms 0.001 Å、
   `all_precision 1.0`，而 `model_transplant.r1_on_reference_data = 0.4227`、
   `verdict: "model itself differs from the reference solution"`（对齐只用了 `r=I,
   t=[0.25,0.5,-0.25]`）。在 P2₁2₁2₁ 的非标准设置 `(a+1/4,b,c-1/4)` ＋ 经过 `invert_structure`
   换手之后，移植的原点 / 手性对齐大概率没做对。**本格没有改变等级**（grade 仍为 publication），
   但这是评分器的假警报源，**成因未能定位**。
3. **纯工具臂那次电荷翻转最终是"算完了"还是被进程回收掉的**：最后一次可见状态是 7 545 s
   仍在跑（18:04:47），此后没有日志。
4. **收尾裁决为何没进 `verdict.json`**：`sse.jsonl` 止于主回合 `turn_completed`（seq 2961），
   收尾回合的事件没被采集；是 runner 在 turn 中断后不再推进 sse_cursor，还是收尾回合走了另一条
   通道，**未能从这两格的日志判定**（需看 runner 代码，超出本次只读范围）。
5. **`n_phase_sets:100` 对纯工具臂第一次 SHELXT 有没有影响**：那次调用 0.008 s 就因元素清单
   失败，参数没生效，所以无法判断它是否会踩"加大 -m 反而更早被杀"的坑。

---

## 7. 工具侧优化点清单

按"本泳道的损失大小"排序；每条附证据行。

**P0，直接造成 no_delivery**

1. **给 `solve_charge_flipping` 加墙钟上限 + detach/job_status + 服务端取消**。
   现状：schema 里没有 `timeout_s`，`run()` 的 `for seed in seeds: charge_flipping.loop(...)`
   全程没有时钟（`crystalpilot/tools/solution_tools.py:97-135`）。
   *证据*：org-tools-r1 3.29 min 发出 → 68.30 min 客户端 3 900 s 超时 →
   129.05 min 仍被告知 `(running 7545s so far)`；对照 `run_shelxt` 已有
   timeout_s / detach / job_status / phasing_grace_s 四件套（其 description 里整段 BUDGET 说明）。
2. **客户端放弃调用时取消服务端计算（或至少释放项目锁）**。
   *证据*：`run_shelxt` 98.79 min 收到 `gave up waiting after 1810s: 'solve_charge_flipping'
   (running 5729s so far)`；`get_project_brief` 129.05 min 收到 `(running 7545s so far)`；
   `QUEUE_MAX_S = 1800.0`（`crystalpilot/mcp/server.py:46`）使后续每次调用都先烧 30 min。
3. **把预算量级写进 `solve_charge_flipping` 的 description 与 schema，并删掉那句诱导**。
   现状 description 末句 "**try more seeds** or different d_min on failure"；
   `max_attempts_per_seed`（默认 2）与 `max_solving_iterations`（默认 400）
   **两个参数在 schema 里都没有 description 字符串**。
   *证据*：org-tools-r1 传 8 种子 × 20 尝试 × 5 000 迭代（默认的约 1 000 倍总预算），
   两臂 dump 出的 TS 声明里这两个参数都是裸的；那句反向忠告
   （"blind d_min/seed scans have a poor record (r13: 3 runs, 10 min, zero yield)"）
   只写在**失败返回**的 hint 里，org-full-r1 3.67 min 收到并照办，org-tools-r1 永远收不到。
4. **修低完整度守卫的文案**："keep `timeout_s` SHORT" 指向一个本工具不存在的参数
   （`solution_tools.py:62, 68`）。

**P1，直接造成本格的错误分岔**

5. **`run_shelxt` 的 "no element list available" 改写成可执行的许可**。
   建议文案：`start.ins 声明了 SFAC C H N O（UNIT 1 1 1 1 为占位）。传
   composition='C H N O' 即可开跑；占位组成串只影响 SHELXT 的峰高启发式元素指认，不构成元素
   结论（解出后用 audit_element_assignment 复核）。`
   *证据*：org-tools-r1 2.10 min 的 error 原文 + 2.49 min「数据未提供元素清单，SHELXT 因而
   不能启动」+ 3.15 min "it doesn't require explicit composition"；对照 org-full-r1 1.45 min
   直接传 `composition:"C H N O"` 7.2 s 成功。
6. **摄入时把 ins 的 SFAC 作为"披露的元素猜测"写进会话并在 brief 里回显**。
   *证据*：org-tools-r1 MCP #2/#3 的 `candidate_table` 只有 cell/wavelength/space_group_guess；
   #6 `get_project_brief` 的 `model.element_counts = {}`；#5 `wilson.skipped = "no
   model/composition in the session"`；agent 1.48 min 自己在猜 "I'm wondering if start.ins
   includes SFAC"。
7. **区分"本群无消光条件"与"本群的消光类里没有观测"**，两者现在共用
   `absence_evidence="no_absence_conditions"` / `"no absence conditions"`。
   建议第三态，例如 `absences_absent_from_file`，文案："该群有消光条件（h00: h=2n 等），但文件
   中这些类**一条观测都没有**：典型于已剔除消光的合并数据 / 由 fcf 反推的 hkl；**这对该群是
   正面（非否定）线索**，仍需求解试验确认。"
   *证据*：org-tools-r1 1.30 min 候选表里 `P 21 21 21` 与 `P 2 2 2` 的行**逐字节相同**
   （`n_absent_obs 0, n_violations 0, absence_evidence "no_absence_conditions"`）；
   org-full-r1 9.09 min 采纳 P2₁2₁2₁ 时 `absence_audit` 仍是同一句。
8. **把逐类 E 统计也放进 `reflection_statistics(laue_group='all')` 的 `laue_scan`**
   （现在只有 `screen_space_groups(laue_group='all')` 有）。
   *证据*：org-tools-r1 #5 的 laue_scan 只有 r_int/n_unique/multiplicity；
   org-full-r1 的 screen 里 `P m m m → 0.957 centrosymmetric` 与
   `P 1 2/m 1 → 0.806 non_centrosymmetric` 并列，**这一行就是本格定群的胜负手**。
9. **`friedel = null` 要说原因**："文件已折叠 Friedel 对（`looks_merged` / `p1_multiplicity 1.0`），
   无法给出 Friedel 差证据"。
   *证据*：org-tools-r1 #5 `friedel = null`，同一返回里 `merged_note` 已经知道数据是
   "merged in P1 / Friedel pairs folded"。
10. **`solve_superflip` 的 `symmetry_agreement` 要给逐算符判词而不只给通用注脚**，并在
    `per_operator = []` 时说明 overall 该怎么读。
    *证据*：org-tools-r1 3.02 min 拿到 `{op "-1", agreement 70.74}`（判词写着 "density does NOT
    obey that operator"），13 s 后它把群改回中心对称的 Pmmm；org-full-r1 6.82 min 的
    `overall 63.05` 配 `per_operator: []`，无法解读。

**P2，执行层与交付层**

11. **把 MCP 的心跳 / 进度送到模型上下文**（现在经 `exec`+`wait` 丢失）。
    *证据*：org-tools-r1 136 次 `wait`（cell 18/19/20 = 76/38/22）全是盲等；
    agent 20.28 min "why it waits without showing the nested tool progress"、
    56.05 min "notifications might not forward properly"。
12. **明确回报"当前没有待审批项"**（哪怕只在 brief 里加一行）。
    *证据*：org-tools-r1 在 35.61 / 70.78 / 77.27 / 86.83 / 95.43 min 五次假设"可能在等审批"，
    而整份 rollout 的审批类记录为 **0** 条；两臂契约里那句"表现为调用迟迟不返回；照常等待"
    在这种情形下把 agent 钉在原地。
13. **`_symmetry_space_group_name_H-M` 要写得出来**：群带基底注记
    `P 21 21 21 (a+1/4,b,c-1/4)` 时，`change_space_group("P 21 21 21")` 返回同一个注记符号
    （并顺手剥掉 11 个 H），CIF 的该字段最终为空，逼 agent 去 waive 一条 A 警报。
    *证据*：org-full-r1 15.18 min 的返回 `old = new = "P 21 21 21 (a+1/4,b,c-1/4)"`,
    `n_h_stripped: 11`；15.40 min 推理 "that doesn't strip because it identifies the current
    basis"；`grade.json: self_consistency.cif.space_group = "?"`、checkCIF `A 122`、
    最终 waiver 文案「缺失仅因内部原点注记未转换为旧式 H-M 标签」。
    建议：写 CIF 时输出标准 H-M 符号 + 实际原点位移（或提供 `standardize_setting` 入口）。
14. **候选解的群符号 `"Fp"` 不是 H-M 符号**，应译回 `P 1`（或标注为 SHELXT 内部记号）。
    *证据*：org-full-r1 7.29 min `solutions[0].space_group = "Fp"`（r1 0.072），
    同一返回的 `adopted.space_group = "P 1"`。
15. **战役采集：收尾回合的裁决要进 `verdict.json`**。
    *证据*：org-tools-r1 的诚实裁决在 rollout 的 09:55:53Z（本地 17:55:53）；
    `verdict.json` 却是 `{"unparsed": "状态无变化：原求解仍在运行，没有新节点或错误。继续等待。"}`；
    `sse.jsonl` 止于 seq 2961（主回合 `turn_completed`，`status TurnStatus.interrupted`）。
16. **`state.json` 的 grade 要能被 `--regrade` 刷新**。
    *证据*：`grade.json`（22:55:36）已是 `publication`、`chemistry.flags = []`；
    `state.json`（18:14）仍写 `"grade": "acceptable"`。
17. **`model_transplant` 与 `emma` 在同一份 grade.json 里互相矛盾时应自陈存疑**。
    *证据*：`emma.all_atoms` 13/13、rms 0.001 Å、元素错配 0，而
    `model_transplant.r1_on_reference_data = 0.4227`、`verdict "model itself differs from the
    reference solution"`，对齐仅 `t=[0.25,0.5,-0.25]`、`r` 为单位阵，非标准设置 ＋ 换手后的
    原点 / 手性对齐疑似未处理（成因未定位，见 §6 不确定 2）。

---

### 附：两臂 AGENTS.md 的关键差异（本泳道用到的部分）

| 事项 | `TEMPLATE_TOOLS_ONLY`（3 691 B） | `TEMPLATE` v32（26 445 B） |
|---|---|---|
| `composition` / `SFAC` / `shelxt` 字样 | **各 0 次** | `composition` 见第 181 行（"改搜索"旋钮）；**"占位的 C H N O" 见第 368 行** |
| 筛群口径 | 无 | "劳厄类拿不准时 `laue_group='all'` + `merge_stats=true` 一次给所有类" |
| 求解预算纪律 | 无 | 有，但**只覆盖 SHELXT**（n_phase_sets 钳到 500、detach+job_status、改搜索不改预算）；`solve_charge_flipping` **无预算条款** |
| 技能卡指针 | 无（四个技能工具未注册，工具数 65） | 有（`data-ingest-space-group-protocol` / `framework-solve-ladder` / `flack-absolute-structure` 等；工具数 69） |
| "慢≠卡死 / 绝不杀进程 / 可能在等审批" | **有** | **有** |
| "不编造实验元数据与结构" | **有** | **有** |
| "空间群不做静默改判" | **有** | **有** |
