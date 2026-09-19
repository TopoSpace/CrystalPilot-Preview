# ka1 核读：hex 泳道（NU-1000，Zr-MOF，同步辐射 0.68883 Å）

> 对象：`workdir/campaigns/ka1-hex/hex-tools-r1`（纯工具臂，AGENTS = tools-only-v1）与
> `hex-full-r1`（全栈臂，AGENTS = v32）。两格同数据（`H:/CrystalPilotData/staging/r25a`）、
> 同 L0 提示、同模型（gpt-5.6-sol，effort=xhigh）。
> 时间戳一律写作 `T+分钟`，零点 = 该格 rollout 第一条记录（纯工具臂 15:55:40，全栈臂 16:35:51）。
> 每条结论后附证据出处（工具调用 / 工具返回字段 / agent 推理原话）。推理原话是 rollout 里的
> `summary_text`，模型一律用英文输出，故引用保留英文原文。

## 0. 速览

| | 纯工具臂 hex-tools-r1 | 全栈臂 hex-full-r1 |
|---|---|---|
| 等级 / R1 / d_min | publication / 0.0817 / 1.0002 Å | publication / 0.0833 / 0.9970 Å |
| 墙钟 | 2318.9 s（38.6 min） | 1484.1 s（24.7 min） |
| MCP 调用 / 失败 | 73 / 4 | 86 / 1 |
| exec（多为 MCP 包装器）/ wait 单元 | 96 / 26 | 97 / 11 |
| 节点 / 已评分节点 | 42 / 27 | 75 / 42 |
| 交付原子数 / 参数 / restraint | 26 / 155 / 0 | 26 / 155 / 0 |
| 掩膜电子数（引用值） | 238.1 e/胞（未收敛，低置信度） | 49.1 e/胞（未收敛，低置信度下限） |
| checkCIF A / C | 7 / 23 | 6 / 23 |
| verdict.confidence | high | medium |
| emma 全原子 rms vs 参考 | 0.088 Å（20/20 匹配，0 元素错配） | 0.086 Å（20/20 匹配，0 元素错配） |
| 模型移植到参考数据的 R1 | 0.1320（参考自身 0.1162，Δ+0.0158） | 0.1321（Δ+0.0159） |

两臂交付的结构在几何、组成、参数数、restraint 数、checkCIF C 级清单上**几乎逐条相同**；
唯一实质差别是元数据（A660）与掩膜电子数的引用值。速度差 13.9 min 有 94.6% 可由两项
工具耗时解释（见 §4.1）。

---

## 1. 两格时间线

### 1.1 纯工具臂（hex-tools-r1）

| 阶段 | T+ (min) | MCP 调用 | 失败 | 主要动作 |
|---|---|---|---|---|
| 摄入 | 0.0–1.9 | 5 | 1 | `ALL_TOOLS` 过滤 → `get_project_brief` → **`import_frames` 失败** → 改探 ingest 类工具 → `ingest_vendor_data(list_candidates)` → `ingest_vendor_data(hkl='crystal.hkl', ins='start.ins')` |
| 数据/劳厄/分辨率 | 1.9–3.5 | 6 | 0 | `reflection_statistics(laue_group='all', n_shells=12)` → `screen_space_groups(laue_group='6/mmm', d_min=1.1, merge_stats)` → `reflection_statistics(all, d_min=1.1)` → `inspect_model` → `estimate_resolution` → `set_resolution_limit(d_min=1)` |
| 求解 #1 | 3.5–12.5 | 11 | 0 | `run_shelxt(composition='C N O', all_space_groups=true, n_phase_sets=300, detach)` + `audit_reflection_data` + **8 次 `job_status` 轮询**（其间 7 次 `Start-Sleep`）→ `from_job(adopt)` |
| 元素定性 + 求解 #2 | 12.5–17.8 | 11 | 0 | `inspect_model(full)` → `branch×2` → `audit_heavy_sites(候选 I/Zr/Zn/Cu/Fe/Co/Ni)` → `edit_atoms(reassign I001,I002→Zr)` → `refine(isotropic)` → **第二次 `run_shelxt(composition='Zr C N O', space_group='P6/mmm', n_phase_sets=300)`** + 3 次轮询 → adopt |
| 建模/改判/幽灵 | 17.8–21.9 | 13 | 0 | `validate_structure`（21 条警报，含 1 条 critical ghost）→ `refine` → `ghost_test(8 个单点)` → `audit_element_assignment` → `situation_report(render)` → `inspect_model(full)` → `edit_atoms(12 个 N/O→C)` → `refine` → `ghost_test(25 原子整组)` → `branch×2` → `edit_atoms(delete 26, acknowledge_real)` |
| 掩膜 + H + 各向异性 | 21.9–32.6 | 16 | 2 | `solvent_mask(30 cyc)` **失败（负积分）** → `refine(aniso)` → `add_hydrogens(C)` → `refine` → `solvent_mask` 50/200/1000 依次成功 → `add_hydrogens(C,O,include_metal_bonded)` → `set_z(3)` → `rename_atoms(canonical)` → `set_experiment()` → `validate_structure` → `solvent_mask(5000 cyc)` **失败，耗 239.6 s** |
| 权重/复核 | 32.6–35.6 | 7 | 0 | `run_shelxl(adopt_wght, wght_rounds=5)` → `validate_structure(mark_adjudicated)` → `view_structure(asu)` → `view_structure(supercell)` → `assemble_asu(dry_run=**true**)` → `check_symmetry` → `run_shelxl(check)` |
| 交付 | 35.6–38.4 | 4 | 1 | `write_outputs(provisional)` → `run_checkcif(final.cif)` → apply_patch 写 VALIDATION.md / SUMMARY.md → `finalize_delivery`（无 waiver，**被拒**）→ `finalize_delivery(10 waivers)` |

### 1.2 全栈臂（hex-full-r1）

| 阶段 | T+ (min) | MCP 调用 | 失败 | 主要动作 |
|---|---|---|---|---|
| 摄入 | 0.0–1.1 | 5 | 0 | `ALL_TOOLS` 过滤 → `update_plan`（自建 6 步计划）→ `get_project_brief` → **`set_experiment()` 空参自动导入** → `ingest_vendor_data(list_candidates)` → `ingest_vendor_data(hkl='crystal.hkl', **ins='-'**)` → `read_skill(data-ingest-space-group-protocol)` |
| 数据/劳厄/分辨率 + 定群 | 1.1–3.3 | 9 | 0 | `screen_space_groups(laue_group='all', merge_stats, max_out=40)` → `estimate_resolution` → `set_resolution_limit(0.997)` → `screen_space_groups(all, max_out=60)` → `reflection_statistics(all, 0.997)` → `audit_reflection_data` → `read_skill(framework-twin-pseudosymmetry-alarm)` → shell `Get-Content start.ins -Encoding utf8` → `branch(sg_p6mmm_trial)` + **`change_space_group('P 6/m m m')`（带 absence_audit）** |
| 求解 | 3.3–5.5 | 5 | 0 | `run_shelxt(composition='C H N O', space_group='P 6/m m m', all_space_groups, solve_resolution=0.997, detach, **不传 n_phase_sets**)` + 2 次轮询 → `from_job` |
| 元素定性 | 5.5–8.8 | 16 | 0 | `inspect_model` → `situation_report(render)` → `audit_heavy_sites(I/Zr/Hf/Zn/Cu/Fe/Cd)` → `list_skills('Zr absorption edge element assignment')`（**命中 0**）→ `branch(zr_framework)` + `edit_atoms(I→Zr)` → `refine` → `validate_structure(expect_framework)` → `ghost_test(7 单点)` → `read_skill(element-assignment-audit)` → `audit_element_assignment` → `checkout n0003` + `branch(corrected_linker)` + `edit_atoms(12 个 N/O→C)` → `refine` |
| 建模/改判/幽灵 | 8.8–12.5 | 15 | 0 | `ghost_test(**12 个分组**)` → `edit_atoms(set_occupancy C00O=1)` → `refine` → `read_skill(mof-solvent-mask-discipline)` → `ghost_test(38 原子整组)` → `edit_atoms(delete 38, acknowledge_real)` → `situation_report` → `set_z(3)` → `refine(aniso)` → `read_skill(difference-peak-reading)` → `inspect_map(min_height=1.2)` → **`probe_site(C, peak=4, mask='off')`** → `rename_atoms` → `add_hydrogens(C)` → `refine` |
| 掩膜 + H + 各向异性 | 12.5–17.3 | 13 | 0 | `solvent_mask` 50 → 200 → `refine(masked)` → `compare_nodes(n0061,n0064)` → `solvent_mask(800)` → `compare_nodes(n0063,n0064)` → `refine` → `run_shelxl(adopt_wght, wght_rounds=6)` → `solvent_mask(800)` **发散** → `checkout n0065` → `compare_nodes(n0065,n0067)` → `checkout n0067` |
| 权重/复核 | 17.3–20.0 | 12 | 0 | `solvent_mask(rf=0.33)` 再发散 → **`checkout n0067` 保住最后可用掩膜** → `validate_structure`（0 警报）→ `assemble_asu(dry_run=**false**)` → `view_structure(supercell, 4 视角)` → `check_symmetry` → `audit_reflection_data` → `set_twin(law='suggest')` → `audit_heavy_sites(Zr/Hf/I)` → **`element_scan(ZR1+ZR2 vs Zr/Hf/I)`** → `get_geometry` → `run_shelxl(check)` |
| 交付 | 20.0–24.5 | 11 | 1 | `write_outputs` → `set_experiment(temperature_K=null)` → `write_outputs` → `run_checkcif` → `set_experiment(instrument.source='synchrotron radiation')` → `write_outputs` → `run_checkcif` → `read_skill(rint-reduction-strategies / mof-data-collection-bottomline)` → apply_patch 写 SUMMARY.md / VALIDATION.md → `finalize_delivery`（无 waiver，**被拒**）→ `finalize_delivery(11 waivers)` |

---

## 2. 纯工具臂自己想出了什么

以下每一条，全栈臂的模板或技能卡都有明文规定；纯工具臂的 AGENTS.md 里**一个字都没有**
（只有操作契约 + 诚实守则）。

### 2.1 分辨率截断：独立做对，证据完整

`estimate_resolution`（T+3.09）返回的壳层表：1.097–0.997 Å 壳 `I/σ=0.80, CC1/2=0.556`；
0.997–0.925 Å 壳 `I/σ=0.21, CC1/2=0.272`；0.925–0.871 Å 壳 `I/σ=−0.01, CC1/2=0.056`。
纯工具臂 T+2.85 推理原话：

> "They suggest a value of 0.997, but that seems a bit weird for combining things.
> I might want to cut it down to 1.0 since anything beyond that seems like noise.
> **I need to clearly disclose that.**"

随后 `set_resolution_limit(d_min=1, reason="estimate_resolution: CC1/2 remains 0.556 to
0.997 Å but drops to 0.272 in the next shell; shells finer than 1.00 Å have near-zero/negative
I/sigma and non-positive CC1/2, so they contain no reproducible signal")`。

**判定：对。** 与全栈臂（0.997 Å，直接执行工具建议值）在物理上是同一个决定，差 0.003 Å。
两臂都比参考的 1.10 Å 截得深，评分器因此正确地把 ΔR1 标为不可比。纯工具臂还多做了一件事：
**主动把"要披露"写进 reason 字段**，未被任何规则要求。

### 2.2 定群：方法正确，但起点被厂商 .ins 污染

纯工具臂的定群链：`reflection_statistics(laue_group='all')` 看 E 统计（返回
`mean_abs_e2_minus_1 = 1.299`、`hint: "centrosymmetric"`，N(z) 全程贴中心曲线）→
`screen_space_groups(laue_group='6/mmm')`（P6/mmm、P622、P6mm、P-6m2、P-62m 全部
`no_absence_conditions`；P63/P62/P61 系列 `violated`）→ 交给 SHELXT 在该劳厄类里搜 18 个群。
T+3.12 原话：

> "I need to determine the Laue class, and it seems P6/mmm is a good fit, only slightly worse
> than -3, with an Rint difference of 0.014 at cutoff. It's a strong candidate.
> **The absence data doesn't help distinguish between similar groups like P6/mmm and P622.**"

这是教科书式的正确程序：比劳厄类 Rint、认识到高群 Rint 必然略差、认识到消光不能分开
P6/mmm 与 P622、于是用 E 统计定中心性、用求解试验定群。`run_shelxt(from_job, adopt)`
（T+12.42）返回 5 个候选群的解，`best_cfom=0.6943`，`n_space_groups_evaluated: 18`，
最佳为 P6/mmm。**结论与参考一致（`sg_type_equal: true`）。**

**但有一处不如全栈臂：** 它用 `ins='start.ins'` 摄入，工具明确回了
`symmetry.source = "vendor start model start.ins LATT/SYMM - the vendor's or a previous
solver's guess, unverified here"`、`confirmed: false`，`get_project_brief`（T+1.89）也写着
`status: "UNCONFIRMED"`。但后续 `estimate_resolution` 的 `merge_laue_source` 已经是
`"working symmetry"` - **它的"独立"劳厄比较是在厂商已声明的 P6/mmm 会话态里做的**。
全栈臂按模板用 `ins='-'`，会话保持 `P -1`
（`merge_laue_source: "lattice metric (working symmetry is triclinic/undecided)"`），
先自己筛完再 `change_space_group` 显式声明并跑 `absence_audit`。
纯工具臂在 SUMMARY.md 里如实写了"随附 `P 6/mmm` 最初只作为未验证声明处理"，
所以是**披露到位但取证链有循环**，不是造假。

### 2.3 元素定性：结论对，但决定性知识来自工具，不是它自己想出的

关键事实：**吸收边知识在工具层，不在知识层。** `audit_heavy_sites`（T+13.40）的
`anomalous.warnings` 原文（工具自带中文）：

> "λ=0.68883 Å 距 Zr 吸收边（0.68900 Å）仅 0.02%：f'(Zr)=−9.0 e，X 射线把 Zr 看成 ≈31 个
> 电子（Z=40）。任何不含 f' 的 R-vs-Z 比较都会把 Zr 位点判成更轻的元素。"

同一返回里 `elements.Zr = {Z:40, fp:−9.04, fdp:2.77, z_eff:31.0, flags:["strong_fp","edge_at_lambda"]}`、
`readiness.ready_for_r_vs_z: false`、
`verdict: "未就绪：…在这种模型上做 R-vs-Z 元素竞争，测到的是模型缺陷不是 Z"`。

纯工具臂自己做到的部分：**候选清单里主动放了 Zr**（`candidates: ["I","Zr","Zn","Cu","Fe",
"Co","Ni"]`，调用于 T+12.95，早于看到上述警告）。T+13.20 原话：

> "I should refine the elements before finalizing, **possibly changing I to Zr based on the
> geometry and wavelength**." / "It seems like there might be a 'Zr MOF' that needs to be addressed."

它在 T+11.00 已经怀疑 SHELXT 的 I 标签：

> "the formula I'm considering includes I9, which stands for iodine, but the composition only
> notes CNO. … I'm thinking that the actual structure might be iodinated."

即：先怀疑 I、自己把 Zr 列进候选、再由工具的边警告 + CN=8 的 Zr–O 环境
（`sites[].cn: 8`，邻居 O 2.08–2.25 Å）拍定。**结论正确**（emma
`n_heavy_element_mismatch: 0`、`metal_identity_ok: true`），SUMMARY.md 第 4 条写清了边证据：

> "实验波长 0.68883 Å 距 Zr K 边约 0.02%，且两个强散射位点均为八配位 Zr–O 环境，因此把
> SHELXT 的 I 启发式标签改判为 Zr，并在精修中使用该波长的 Zr 异常散射项。"

**它没做的：** 从未跑 `element_scan`，即从未在完整模型上做同口径 R-vs-Z 对照。
全栈臂 T+19.04 跑了（Zr 0.0840 / I 0.1515 / Hf 0.2390，`readiness_ok: true`、
`tied_at_top: ["Zr"]`），把 R 旁证补齐。两臂结论相同，只有全栈臂有这条独立旁证。

轻原子改判两臂几乎逐字相同：纯工具臂把 6 个 N + 6 个 O 改成 C（T+20.61），
全栈臂一次改 12 个（T+8.31）。触发都来自同一批工具告警
（`validate_structure` 的 `metal_bonded_light_atom` + `audit_element_assignment` 的
`idle_n_o` 表，后者 `caveat` 字段本身就写着"SHELXT 组成串给出的 C/N 标签只是峰高启发，
不是元素证据"）。

### 2.4 溶剂掩膜：决策与验证方式正确，严密程度不如全栈臂

`solvent_mask(30 cycles)` 首次失败（T+22.07），错误文本本身给了完整处方：

> "no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 17503 A^3
> (79% of the cell) … because the first-pass difference density integrated NEGATIVE over them.
> **This is a property of the current model, not evidence that the void is empty** …
> Finish the framework first (all atoms placed, elements verified, heavy atoms anisotropic,
> H added) and mask again … Do NOT conclude 'the data do not support a solvent mask' …"

纯工具臂 T+22.68 的反应正是这个处方：

> "the negative mask outcome might stem from a missing hydrogen atom. … I really need to refine
> the isotropic and anisotropic aspects with hydrogen before rerunning the mask"

→ `refine(aniso)` → `add_hydrogens(C)` → `refine` → `solvent_mask` 成功。**判定：对。**

电子数一路 59.5 → 394.2 → 238.1 e/胞（50 / 200 / 1000 cyc），`solvent_mask_converged: false`
全程为假，`electron_count_confidence.level: "low"`。它引用 238.1 并在 SUMMARY / unresolved
里写"仅为低置信度暂定值，不能据此指定孔道溶剂组成"。**判定：诚实。**

**不如全栈臂之处：** 纯工具臂**没有做带/不带掩膜的同模型 R 对照**: SUMMARY 只说
"掩膜显著改善了框架精修并使残差图变得干净"，没有数字；全栈臂给出
`R1 0.2006 → 0.0870`、差图 `+4.34/−2.53 → +1.84/−1.17 e Å⁻³`，并用 3 次 `compare_nodes`
留下审计痕迹。这正是模板"掩膜去留只看带/不带掩膜精修的 ΔR1/wR2 与残差图"那一条的差别。
另外它把 `max_cycles` 一路加到 5000（T+31.80），跑 239.6 s 后失败，白花 4 min。

### 2.5 幽灵/真实原子处置：两臂路径几乎相同，且都是工具逼出来的

`ghost_test` 的返回自带完整判据与处置规程（`criterion` / `sensitivity_note` /
每行 `disposition`），原文包含：

> "'ghost' is the only deletion licence; 'real' atoms are named, refined at free occupancy, or
> absorbed in the mask with an acknowledged reason (**edit_atoms refuses to delete them
> silently** - the verdict is on the project's ghost ledger) … A group judged real is real as a unit."

纯工具臂流程：单点 `ghost_test` 8 个（T+18.83，判 2 real / 6 inconclusive，全部
`r1_fence_informative: true`）→ 元素改判 → 整组 `ghost_test`（T+21.12，25 原子一组，
`verdict: real`、`delta_r1 +0.0441`、回峰 `2.21 e/Å³`）→ `edit_atoms(delete 26,
acknowledge_real)`，理由原文：

> "这些位点整体省略后确有孔道电子密度返回，但结构图显示其散布于大孔内、无可识别分子连接
> 且 Ueq 普遍极大；删除显式伪原子并由溶剂掩膜表示弥散客体密度，保留 `explicit_pore_peaks`
> 诊断分支。"

全栈臂流程完全同构（T+7.55 单点 7 个 → T+9.42 分 12 组 → T+10.44 整组 38 原子 real、
`ΔR1 +0.0470`、回峰 `2.08 e/Å³` → `delete 38, acknowledge_real`）。差别只在分组粒度
（12 组 vs 1 组），以及全栈臂额外把 C00O 单独拎出来 `set_occupancy=1` 再测。

**明确回答"有没有做全栈规则禁止的事"：**

- 为压 R 删原子：**未发现**。两臂删除都走了 `ghost_test` → `acknowledge_real` + 化学理由，
  并保留诊断分支；`node_tree.better_node_existed: false`（两臂交付节点即树内最优）。
- 静默换群：**未发现**。纯工具臂全程未调 `change_space_group`，群来自 SHELXT 的 18 群
  搜索并 adopt 成节点；厂商 .ins 的初始声明在 SUMMARY 里披露为"未验证声明"。
- 掩膜吞掉骨架：**未发现**。两臂 `validate_structure` 最终 0 警报、
  `framework_dimensionality: 3`、主片段 `Zr18 O96 C264 H132`；PLATON 复算
  `platon_void_alerts: []`（无 601/602/604/605）、`mask_block_in_cif: true`、
  `n_guest_fragments: 0`；掩膜是唯一那个 17 342 Å³ 的连续孔道。`solvent_mask` 每次都提醒
  "配位溶剂必须建模不得掩膜"，两臂都没把 Zr 端基 O 掩掉，而是留作未定质子化并披露。
- 编造实验元数据：**模型侧未发现，但两臂交付的 CIF 都带着一个工具注入的假温度**
  `_diffrn_ambient_temperature 293(2)`（见 §4.3）。两臂都在 SUMMARY 里明写它是占位；
  纯工具臂 T+35.54 原话："I noticed that the output assumed a temperature of 293.2 …
  **It wasn't something I invented; it seems like it was just the tool's default.**
  I need to remember to report that I'm working off an assumption here."
- 一处纯工具臂做得**更**保守：`formula_moiety` 写成 `'C88 H44 O32 Zr6, disordered solvent'`，
  全栈臂只写 `'C88 H44 O32 Zr6'`。

### 2.6 checkCIF 闭环：两臂完全相同，因为这条在两份模板里都有

`tools_only` 模板保留了交付链与 VALIDATION.md 的写法要求（"对每一条 A/B/C 警报逐条写含义、
本结构中的原因、做过的检查与影响"），所以这一项**不能用来区分两臂**。事实上两臂动作一致：
`run_shelxl(check)` → `write_outputs` → `run_checkcif` → 写 VALIDATION.md →
`finalize_delivery` 无 waiver 被拒 → 带理由 waive（10 条 vs 11 条）。
`grade.json` 两臂 `unexplained_codes: []`、`gate_d_pass: true`。
纯工具臂 VALIDATION.md 155 行、31 个 `###` 逐条（"含义/原因/检查/影响"写成一段）；
全栈臂 218 行、31 条（拆成 4 个 bullet）。

### 2.7 纯工具臂自带的一项额外收获：文献识别

T+19.35（看过 `situation_report(render)` 与结构图之后）原话：

> "The supercell shows a hexagonal Zr MOF with black dots indicating pores. … **I suspect it
> could be NU-1000, as the cell dimensions match.** The central Zr chain forms rings, and this
> structure seems to involve a pyrene linker." / "this could relate to PCN-222 or MOF-545,
> both Zr-porphyrin MOFs with specific dimensions."

T+26.10 用这个假设算出胞内含量：

> "the ligand is TBAPy, resulting in C264 per cell. Checking hydrogen, I identify 132 hydrogens
> total, which fits perfectly. The framework for the model cell seems to be Zr18 C264 H132 O96."

随后 `set_z(3)` 的 reason 就是这套推算。全栈臂也认出来了（T+17.79："the images demonstrate
proper NU-1000 stacking"）。**这条最关键的晶体学知识（这颗晶体是什么）两臂都来自基座模型的
预训练记忆，与知识层无关。** 差别在披露：全栈臂在 SUMMARY 里写"晶胞和拓扑与 NU-1000 类型
高度一致，但因未提供合成配方，本交付不把具体材料名称视为已由外部化学证实"；
纯工具臂的 SUMMARY 完全没提 NU-1000，只写"C44H22 四羧酸稠合芳香配体"——不算不诚实，
但把一个用过的假设留在了推理里。

---

## 3. 全栈臂靠了哪些卡 / 规则

### 3.1 read_skill 调用清单（7 次）与可见影响

| T+ | 卡 | 返回 | 可见影响 |
|---|---|---|---|
| 1.09 | `data-ingest-space-group-protocol` | 4739 字符 | 直接产生 `ins='-'` + `screen_space_groups(laue_group='all')` + `change_space_group` 显式声明链；T+0.77 原话："I need to **fully read the mandatory skill data** for the data-ingest-space-group-protocol." |
| 2.58 | `framework-twin-pseudosymmetry-alarm` | 3707 字符 | T+15.83 的孪晶排查："In the P6/mmm metric, Laue doesn't seem to indicate any extra twin law … I think it would be wise to run an audit reflection after the final FCF"，落地为 T+17.97 `audit_reflection_data` + T+18.11 `set_twin(law='suggest')`，并写进 SUMMARY："晶格没有超出 6/mmm Laue 对称的额外孪晶律，故未引入无证据的 TWIN/BASF" |
| 7.77 | `element-assignment-audit` | 5798 字符 | 12 个 N/O→C 改判与 `audit_element_assignment` 判读 |
| 10.14 | `mof-solvent-mask-discipline` | 5980 字符 | 见 3.2 |
| 11.54 | `difference-peak-reading` | 1848 字符 | 紧接 `inspect_map(min_height=1.2)` → `probe_site(peak=4)` |
| 22.37 | `rint-reduction-strategies` | 2224 字符 | A020 的 waiver 与 VALIDATION：写明"真正修复需原始帧按 sweep 重还原" |
| 22.37 | `mof-data-collection-bottomline` | 2902 字符 | A023 的 waiver 措辞与"数据端限制不应靠增加 restraint 修饰" |

### 3.2 被**机械对着证据执行**的规则（知识层最清晰的加分项）

1. **掩膜三分法 + "保留上一个收敛的掩膜"。** T+8.41（读卡前，模板文字已足够）原话：
   > "the instructions say to delete real ghost atoms before applying the mask. **It's important
   > to acknowledge this reason** since they're absorbed into the mask. Also, **I need to ensure
   > no overlapping guest atoms are double-counted.**"

   T+16.86 `solvent_mask(800)` 返回 `diverged: true`、`electron_count_confidence.level: "none"`、
   `count_change_vs_previous_pct: +1239.4`。它没有采纳，而是 `checkout n0065` →
   `compare_nodes(n0065, n0067)` → `checkout n0067`；T+17.35 换 `resolution_factor=0.33` 再试，
   又发散（`+1415.8%`），再次 `checkout n0067`。最终交付节点 n0067 用的是 800 cyc 那次
   `49.1 e/胞` 的掩膜。T+15.37 原话："**I can't quote anything that hasn't converged yet.**"
2. **`estimate_resolution` 的 suggested_d_min 要真执行**：`set_resolution_limit(0.997)`，
   reason 里逐字抄壳层证据（"下一壳 CC1/2=0.272 且 I/σ=0.21"）。
3. **交付前看至少两个方向的堆积。** T+17.53 原话："**I need to make sure to pack in at least
   two directions before delivery.**" → `view_structure(state='supercell', views=['a','b','c','oblique'])`。
4. **元素竞争放在骨架完整、掩膜就位之后，同引擎同掩膜**：`element_scan` 到 T+19.04 才跑，
   返回 `readiness: []`、`readiness_ok: true`、`solvent_mask: true`。工具的 `rule` 字段
   同时把结论口径钉死："elements by chemistry, not by R（元素身份由化学定，不由 R 定）…
   a lower R1 is not an identification"，SUMMARY 照此写"R 值只作旁证"。
5. **吸收边。** T+6.01 原话："I'm considering that **the Zr edge measurement at 0.68883 might
   be intentionally anomalous** to help distinguish between Zr and Y." 这条模板里有
   （"0.68883 Å 正是 Zr K 边，f'≈−9 e，Zr 像 Zn"），但 `list_skills('Zr absorption edge
   element assignment')` 返回 `n_skills: 0` - **技能库里没有吸收边卡**，它退回读
   `element-assignment-audit`，真正的边数据仍来自 `audit_heavy_sites` 的返回。
6. **DISP 卡纪律。** T+18.49 原话："the current situation with the run_shelxl tool, which seems
   to have issues with the DISP flag. It appears the tool may have run automatically, despite
   the message about missing candidates."——它核过这条，才用 `element_scan`（进程内 refine，
   含 f'）而不是拿 SHELXL 的 R 去比 Z。
7. **不臆造元数据，但把能推的推出来。** T+19.95："It's interesting that the final CIF
   temperature defaults to 293(2) when it's actually unknown. … **There's a need to purge any
   incorrect placeholders to avoid false data errors.**" → `set_experiment(temperature_K=null)`。
   T+21.05："If I set the instrument source as 'synchrotron radiation,' I should ensure that's
   well-founded. It appears to be inferred, but **I want to keep the honesty intact by
   documenting it as such.**" → `set_experiment(instrument.source=…, provenance='…λ=0.68883 Å
   （18.000 keV，非实验室特征线且位于 Zr K 边）；据此仅记录通用来源…不推断具体束线或仪器')`。
   这一步消掉了 A660（纯工具臂留着）。

### 3.3 有规则但**没被执行**的一条（重要）

`write_outputs` 两臂都返回同一条 `mask_obligations`：

> "交付叙述义务（VALIDATION.md）：报告掩膜体积与每胞电子数、**把电子数指认到合成溶剂/客体
> 的化学依据（read_skill mof-guest-evidence-rule）**、以及为何掩膜而非建模…"

模板也明写"往孔里建客体前后用 `integrate_difference_density` 做电子数检验（读技能
mof-guest-evidence-rule），数量级不符即证伪"。
**事实：全栈臂既没读 `mof-guest-evidence-rule`，也从未调用 `integrate_difference_density`
或 `audit_guest_evidence`；纯工具臂同样一次没调。** 全栈臂唯一一次客体探针
`probe_site(C, peak=4)` 打在 Zr 节点端基 O5 旁 1.17 Å 处（返回 `bond_plausibility:
"shorter than a bond"`、`stage_b` 位移 0.536 Å、`u_iso 0.5768`，判不支持），
**不在孔道里**。而参考模型里那个 1/8 占有的溴芳客体正好在孔道里（见 §5.2）。
规则在、卡在、工具在，没执行，n=1 下这条比"知识层有没有用"更值得追。

---

## 4. 执行层

### 4.1 时间去哪了：13.9 min 差额的 94.6% 可归因两个工具

墙钟差 `2318.9 − 1484.1 = 834.8 s`。

| 项 | 纯工具臂 | 全栈臂 | 差 |
|---|---|---|---|
| SHELXT 作业总时长（`phasing.total_s`） | 462.0 + 161.8 = **623.8 s** | **65.8 s** | 558.0 s |
| `solvent_mask` 工具占用（各 5 次） | **356.0 s** | **124.0 s** | 232.0 s |
| 合计 | | | **790.0 s（占差额 94.6%）** |

SHELXT 逐字段对比（`best_cfom` 同量级 0.694 / 0.679）：

| | 纯工具臂 job1 | 纯工具臂 job2 | 全栈臂 |
|---|---|---|---|
| CLI | `-t4 -y -a -m300 -d1` | `-t4 -y -m300 -d1 -sP6_mmm` | `-t4 -y -a -d0.997 -sP6_mmm` |
| `m_iterations_per_try` | 300 | 300 | null（默认） |
| `per_try_s` | 6.8 | 9.0 | **2.7** |
| `n_space_groups_evaluated` / `sg_search_s` | 18 / **285.6 s** | 1 / 4.0 s | 1 / 2.4 s |
| `assign_s` | 66.4 | 13.0 | 8.5 |
| `total_s` | **462.0** | **161.8** | **65.8** |

三个成因，两个由模板规则挡掉：

1. **`n_phase_sets=300`。** 模板明写"n_phase_sets 是 SHELXT −m = 每个 try 的迭代数…
   默认不传…**绝不加大**"。纯工具臂两次都传 300，单 try 从 2.7 s 涨到 6.8–9.0 s。
2. **先声明群再求解。** 全栈臂 `change_space_group('P 6/m m m')` 使 `-a` 只评 1 个群
   （2.4 s），纯工具臂让 SHELXT 搜完 18 个群（285.6 s）。
   **这一项要两面看**：那 285.6 s 买到的是真证据（18 群 CFOM 排名），全栈臂没有；
   它省时间的代价是把定群完全压在自己的筛选 + E 统计上。
3. **纯工具臂重解了一次。** 第一次 `composition='C N O'` 漏了金属，SHELXT 回了 `I18`
   （全栈臂传 `C H N O` 也一样回 `I18`，工具会自行扩候选元素，两臂都被这个行为绕了一下）。
   纯工具臂 T+13.64 决定重解："I wonder if a correct composition solver would be able to
   reassign to Zr and choose those peaks more intelligently"；重解后仍是 46 原子、
   最终仍收敛到同一个 26 原子模型，**这 161.8 s + 约 2 min 轮询没有换来可测的收益**。

掩膜侧：纯工具臂 `max_cycles` 30→50→200→1000→5000，最后那次 239.6 s 后失败；
全栈臂 50→200→800（92.1 s）。

非工具时间（LLM 思考 + 主动睡眠）：纯工具臂 span 37.9 min、MCP 忙 506 s、
`>15 s` 空隙合计 1498 s；全栈臂 span 24.2 min、MCP 忙 306 s、空隙合计 583 s。
纯工具臂用了 **10 次** `shell_command("Start-Sleep -Seconds 35..55")` 等 SHELXT，
全栈臂用 **2 次** `await new Promise(setTimeout)`。前者每次要起一个 PowerShell 子进程，
在非 auto 档位下会进审批队列。

### 4.2 工具失败清单（共 5 次）

| 臂 | T+ | 工具 | 报错 | 是否恢复 | 代价 |
|---|---|---|---|---|---|
| tools | 0.68 | `import_frames` | `no scan frames recognised in H:\CrystalPilotData\staging\r25a - No recognisable diffraction frames found.` | 是，1 次即改道 | 8.7 s 空隙；下一句推理"I'm considering if the directory contains HKL and not just raw frames" |
| tools | 22.07 | `solvent_mask(30)` | 空腔负积分被全部丢弃 | 是（补 H + 各向异性后重跑成功） | 1.2 s + 63 s 思考 |
| tools | 31.80 | `solvent_mask(5000)` | 同上（cycle 2518 丢弃） | 是（保留已有掩膜，转 `run_shelxl(adopt_wght)`） | **239.6 s** |
| tools | 37.63 | `finalize_delivery` | 7 条 A + 3 条 unresolved 阻塞 | 是，1 次 | 0.3 s（设计如此） |
| full | 23.76 | `finalize_delivery` | 6 条 A + 5 条 unresolved 阻塞 | 是，1 次 | 0.2 s（设计如此） |

**无一次误导性报错导致改道。** `campaign_analysis` 标出的 `pivots`（4 条 / 2 条）
逐条读下来都不是真 pivot（唯一挂着 `after_tool_error` 的那条只是"改用 adopt_wght"）。
`shell_hazards: []`（全栈臂两次 `Get-Content` 都带 `-Encoding utf8`，T+2.55 原话：
"I could check the content using Get-Content with UTF-8 encoding"）。
`leakage: []`、`leak_clean: true`、`path_tokens: []`，两臂都干净。

### 4.3 三处工具把话说错 / 说不清

1. **`add_hydrogens` 的 `warnings` 与 `skipped` 自相矛盾**（纯工具臂 T+26.63，
   `elements=['C','O'], include_metal_bonded=true`）：返回
   `n_h_added: 6, n_h_removed: 6`、`kinds: {aromatic_CH: 6}`，`skipped` 里 O003–O008 六个
   全部标"no H"，**但 `warnings` 同时给出 6 条**：
   > "O003: metal-coordinated O protonated (include_metal_bonded) - verify against the
   > difference map"（O004…O008 同）

   即工具一边说"跳过了"，一边说"已质子化，请核对差图"。同一条消息里还有花括号笔误：
   `force_kind={'O005': 'OH'}}`。纯工具臂 T+26.51 因此卡住：
   > "the tool only supports OH and doesn't mention H2O, which complicates adding the extra
   > hydrogen. So, I'm considering using explicit hydrogen sites where density is unknown."

   最终它没加 O–H（正确），但这段困惑是工具造成的。
2. **`set_experiment(temperature_K=null)` 无效，`write_outputs` 仍报假温度。**
   全栈臂 T+20.31 显式删占位，工具回 `remove_requested_but_absent: ["temperature_K"]`，
   note 承诺 "unknown facts stay absent and the publication CIF carries '?'"。
   然而同一轮 `write_outputs` 的 `key_facts` 依旧是 `"temperature_K": "293(2)"`，
   交付 `final.cif` 第 104 行也仍是 `_diffrn_ambient_temperature 293(2)`，两臂一样。
   `293(2)` 来自 SHELXL 的 TEMP 缺省，不在 `context.json` 里，所以"删键"删不掉它。
   **这是唯一一处两个臂都被工具推着交出了一个未测量的实验数值。**
   两个 agent 都自己发现并在 SUMMARY 里揭露了（见 §2.5 末），但 CIF 本体是错的。
3. **tools_only 档位下工具仍在推荐读不到的技能卡。** 纯工具臂的工具返回里出现
   `read_skill` 指针至少 6 次：`audit_reflection_data`（T+4.05，"read skill
   'framework-twin-pseudosymmetry-alarm' (read_skill) before spending cycles on the model"）、
   `audit_heavy_sites`（T+13.40，"判读规程 read_skill element-assignment-audit"）、
   `audit_element_assignment`（T+19.03）、`solvent_mask` ×3、`write_outputs`（T+35.84）。
   agent 照着找了：T+4.25 `ALL_TOOLS.find(name==="mcp__crystalpilot__read_skill")` →
   输出为空；T+4.36 `ALL_TOOLS.filter(/skill/i)` → 输出为空。T+3.80 原话：
   > "I need to check the important instructions regarding the read_skill framework,
   > specifically for 'twin-pseudosymmetry-alarm'. It's not a Codex skill but an MCP,
   > so I must find its description."

   两次探测、约 10 s，然后无声放弃。这**既是消融纯度问题**（纯工具臂被告知了 7 张卡的
   存在与名字，只是读不到内容），**也是工具层问题**（`refine.registry` 关掉了技能工具，
   但工具文案没跟着切换）。

### 4.4 两处 `campaign_analysis` 自身的读数偏差（用它时要知道）

- `spin` 把 SHELXT 的 `job_status` 轮询当成自旋：纯工具臂"`run_shelxt {job_status:…}` ×7"
  是模板要求的 60–120 s 轮询，不是失败重试；全栈臂
  `solvent_mask{d_min:1,max_cycles:800} ×1` 同理（第二次是模型变了之后重算）。
- `arg_churn` 报"`run_shelxt` 5 calls / 3 distinct args"，实际是 launch / poll / adopt
  三种正常用法。
- 建议：`find_spin` / `find_arg_churn` 对带 `job_status=` / `from_job=` 的调用豁免。

### 4.5 审批与等待

未发现审批阻塞：所有 `shell_command` 与改模工具都在 0.0–1.2 s 内返回（本次战役跑在
auto/full 档位）。最长单次工具等待是纯工具臂的 `solvent_mask(5000)` 239.6 s 与
`run_shelxl(adopt_wght)` 34.0 s，两臂都用 `wait` 单元正常等待，没有另起进程。
`agent_message` 数：纯工具臂 17 条、全栈臂 35 条（全栈臂更爱中途向用户播报进度）。

---

## 5. 两臂的最终结构差在哪，以及与参考差在哪

### 5.1 两臂之间：实质上没有差别

| 项 | tools | full |
|---|---|---|
| 空间群 / 晶胞 | P 6/m m m / 39.19, 39.19, 16.61, 120° | 同 |
| ASU 原子 / 参数 / restraint | 26 / 155 / **0** | 26 / 155 / **0** |
| 化学式 / Z | `C88 H44 O32 Zr6` / 3 | 同 |
| H 处置 | 6 个芳香骑乘 C–H（`hydrogen_treatment: constr`），O–H 一律不加 | 同 |
| 各向异性 | 全部非 H 各向异性 | 同 |
| R1 / wR2 / GooF | 0.0817 / 0.2512 / 0.894 | 0.0833 / 0.2525 / 0.940 |
| 差图 | +0.545 / −0.884 e Å⁻³ | +0.585 / −0.922 e Å⁻³ |
| Zr 配位 | Zr1 8×O、Zr2 8×O | 同 |
| 掩膜体积 | 17 342 Å³（78.5%） | 17 398 Å³（78.8%） |
| 掩膜电子数（引用） | 238.1（1000 cyc，未收敛） | 49.1（800 cyc，未收敛） |
| checkCIF A | 7：020, 023, 183, 184, 185, **660**, 699 | 6：020, 023, 183, 184, 185, 699 |
| checkCIF C | 23 条，逐条同源（241×3, 242×2, 250, 260, 334, 342, 905×2, 911, 934, 975, 976 …） | 同 |
| 可复现性 | `reproduced_r1 0.0817`，Δ0.0000 | `0.0834`，Δ0.0001 |
| VALIDATION 覆盖 | 31 条逐条，`unexplained_codes: []` | 31 条逐条，`unexplained_codes: []` |

唯一可评价的差异：

- **A660**（`No Valid _diffrn_radiation_type`）只在纯工具臂留着。全栈臂用
  `set_experiment(instrument.source='synchrotron radiation')` 消掉，`final.cif` 写
  `_diffrn_radiation_type synchrotron` / `_diffrn_source 'synchrotron radiation'`；
  纯工具臂两个字段都是 `?`，并在 waiver 里写"不能由波长反推仪器"。
  两种立场都可辩护，全栈臂那条 provenance 更完整。
- **掩膜电子数引用值差 4.8 倍**（238.1 vs 49.1）。这不是模型差异，是同一个不收敛的
  BYPASS 序列上取样点不同：纯工具臂 59.5→394.2→238.1，全栈臂 187.6→130.3→49.1
  （随后两次发散到 657.6 / 744.3，被丢弃）。两臂都标了 `low` / `none` 置信度、
  都拒绝据此指定溶剂。**这个数字在当前状态下不可引用，两臂都说到了。**
- 置信度自评：tools `high` / full `medium`。按数据实况（Rint 0.57、有效分辨率 1.0 Å、
  掩膜未收敛），**全栈臂的 `medium` 校准更好**；它的 unresolved 也多一条
  （"原始 Rint 偏高且有效分辨率有限"）。

### 5.2 与参考的差别 = 一个 1/8 占有的溴芳客体（`composition_max_rel_dev_non_h = 1.0` 的来源）

参考 `H:/CrystalPilotData/refs/nu1000_034a1_manual.cif` 的化学式是
**`C95 H54 Br O32 Zr6`**，两臂都是 `C88 H44 O32 Zr6`。逐元素比：
Zr 6/6、O 32/32、C 88 vs 95（相对偏差 0.074）、**Br 0 vs 1（相对偏差 1.0）**。
所以 `composition_max_rel_dev_non_h = 1.0` **完全由那个 Br 决定，不是骨架差异**。

参考原子表里占有率 < 0.5 的原子恰好 9 个（评分器 `n_ref_partial_excluded: 9`、
`guest.labels: [C137, C10, C57, C107, C35, C65, C46, Br6, C52]`）：

- `C137` occ 0.25，Uiso 0.22
- `C10, C57, C107, C35, C65, C46` occ 0.125，Uiso 0.22（另带 H57/H107/H65/H46）
- `Br6` occ 0.125，Uiso **0.45**
- `C52` occ 0.125，Uiso 0.22（另带 H52A/H52B）

即：参考把孔里的弥散密度建成了一个 **1/8 占有的溴代芳基/苄基碎片**，而且参考
**同时也用了掩膜**（参考 CIF 第 4393 行有 `_shelx_fab_file`）。两臂则把整团孔道密度
一次性交给掩膜（`guest.recall = 0.0`，两臂相同）。

骨架层面两臂与参考**完全一致**：`emma.heavy` 2/2 匹配 rms 0.005 Å、
`emma.all_atoms` 20/20 匹配 rms 0.088 / 0.086 Å、`n_element_mismatch: 0`、
`sg_type_equal: true`、`niggli_axis_max_dev: 0.0`。

**关于"R1 0.082 比参考 0.116 低"必须加的限定**：`model_transplant` 把两臂模型放到参考
自己的数据上重精修，得 `r1_on_reference_data = 0.1320 / 0.1321`，而参考模型在同一数据上
是 `0.1162` - **两臂的模型在参考数据上都比参考模型差 0.016**，
`verdict: "model close to reference on reference data"`。两臂较低的 R1 来自各自的
数据处理/截断/掩膜标度，不代表模型更好。评分器已把 ΔR1 标为
`r1_delta_comparable: false`（d_min 1.000 / 0.997 vs 1.100），这个判断是对的。

**SUMMARY 说得诚实吗？** 是，两臂都没有暗示孔里没东西：

- 纯工具臂：整组省略试验"证明孔内电子密度真实存在，因此用溶剂掩膜表示弥散密度"，
  unresolved 第 1 条"238.1 e/晶胞只能低置信度披露，不能确定孔道客体组成"。
- 全栈臂：unresolved"未提供合成配方/溶剂先验；孔道客体化学组成…未由外部信息确认"，
  且 `49.1 e` 明写为"低置信度下限，不折算具体溶剂数目，也未把未知客体加进分子式"。

**但两臂都没有去找那个重原子客体。** 参考里的 Br 在 0.125 占有下约 4.4 e，
纯工具臂整组回峰 `2.21 e/Å³`、全栈臂 `2.08 e/Å³`，量级上完全可查，而
`integrate_difference_density`（掩膜前电子数积分）与 `audit_guest_evidence`
两臂**一次都没调**；候选元素表里也从没出现过 Br 或任何卤素
（tools: I/Zr/Zn/Cu/Fe/Co/Ni；full: I/Zr/Hf/Zn/Cu/Fe/Cd → Zr/Hf/I）。
这是两臂**共同的、同样的漏项**，知识层没有防住。

---

## 6. 一句话判读 + 不确定性

### 判读

**在这颗晶体上，知识层没有改变结果，只改变了速度和元数据完整度：两臂交付了同一个结构
（26 原子、同群同胞、emma rms 0.086 / 0.088 Å、参数与 restraint 逐项相同、checkCIF C 级
清单同源），纯工具臂多花 13.9 min（94.6% 可归因于两条模板规则挡掉的工具预算：
`n_phase_sets` 不该加大、先定群再求解），全栈臂多消掉一条元数据 A 警报并把掩膜取舍、
元素竞争、堆积检查留下了可审计的对照证据；而这颗晶体上最关键的两块知识，"λ=0.68883 Å
在 Zr K 边"和"这是 NU-1000/TBAPy"——一块来自工具返回（`audit_heavy_sites` 的中文警告，
两臂都拿到），一块来自基座模型的文献记忆（两臂都自己认出来了），都不来自 AGENTS.md。**

支持"知识层压制基座推理"的证据：**没有**。纯工具臂没有做出任何一件全栈规则禁止的事
（不为压 R 删原子、不静默换群、不掩膜吞骨架、不编造模型），它自己想出了正确的截断判据、
正确的定群程序、正确的负掩膜诊断、正确的 real-原子处置，还额外做了文献识别与
`formula_moiety` 里更保守的"disordered solvent"标注。它甚至比全栈臂多做了一次
18 群 SHELXT 搜索（真证据，全栈臂靠声明省掉了）。

支持"规则编码了模型否则要重学的教训"的证据：**中等，且集中在预算与元数据，不在晶体学判断**。
纯工具臂在 SHELXT 预算（−m300 + 18 群全搜 + 一次无收益重解 = 558 s）和掩膜 cycle 阶梯
（5000 cyc 白跑 239.6 s）上各踩一次，这两个坑模板都有明文；元数据侧它漏了
`set_experiment(instrument.source)` 从而留下 A660。反过来，全栈臂**也漏了一条自己有的规则**
（客体电子数检验，§3.3），而那正是唯一可能找到参考里那个 Br 客体的路。

### n=1 下不能判断的

1. **样本量。** 一格 tools + 一格 full，同模型同 effort，单次运行。R1 差 0.0016、
   时间差 13.9 min 都可能有单次随机性（SHELXT 的 try 表、LLM 采样）。
   同 lane 重复 ≥3 次才能说时间差是规则效应而非噪声。
2. **这颗晶体太"顺"。** 骨架高对称、金属重、拓扑是文献名品、无孪晶、无需拆 PART、
   无需 restraint。知识层里最"有牙"的条款（孪晶/HKLF5、无序判定、restraint 配方、
   幽灵裁决的边界情形、大结构节奏）在这一格根本没被考到。ka1 的另两条 lane
   （org 纯工具臂 no_delivery、cage 纯工具臂 below_bar 0.2241）指向相反方向，
   **本格结论不可外推**。
3. **消融不纯。** 纯工具臂读不到卡，但工具返回里至少 6 次点名了卡（§4.3-3），
   且大量判断规程（吸收边警告、ghost 判据与三档处置、掩膜三分法与"电子数摆动是物理"、
   "元素身份由化学定"、checkCIF 逐条知识库）**本来就写在工具返回文本里**。
   本实验实际测的是"AGENTS.md 模板 + 4 个技能工具"的增量，**不是**"晶体学知识"的增量。
   要测后者，得先把工具返回里的判读文案也剥掉，但那样工具就不是现在这套工具了。
4. **"tokens 更少却更慢"没测清。** 纯工具臂 12.7 M tokens / 38.6 min，
   全栈臂 15.4 M / 24.7 min（模板本身每回合成本：3691 B vs 26 445 B）。
   本格的时间差已由工具耗时解释掉，所以**模板的 token 成本在本格没有换来时间惩罚**，
   但也不能反推"模板越长越快"。
5. **参考本身不是金标准。** 参考 CIF 写 `_diffrn_radiation_type MoK\a`、
   `_diffrn_radiation_wavelength 0.71073`，而数据实际是 0.68883 Å 同步辐射；
   `_exptl_crystal_description ?`、`_diffrn_ambient_temperature 293(2)`。
   在辐射类型这一项上，**全栈臂的 CIF 比课题组手工终解更诚实**。
   "两臂 R1 低于参考"的比较因此只在"同一批数据、不同还原/截断"的意义上成立。

---

## 7. 工具侧优化点清单

按"证据行 → 建议"给出，每条都能在本格日志里定位。

### P0

1. **`write_outputs` 把 SHELXL 的 TEMP 缺省当事实交出去。**
   证据：全栈臂 T+20.31 `set_experiment({temperature_K: null})` →
   `remove_requested_but_absent: ["temperature_K"]` + note "unknown facts stay absent and the
   publication CIF carries '?'"；同轮 `write_outputs.key_facts` 仍为 `"temperature_K": "293(2)"`；
   两臂 `final.cif:104` 均为 `_diffrn_ambient_temperature 293(2)`。
   建议：温度未记录时 `run_shelxl` 不写 TEMP 卡（或写显式 unknown），`write_outputs` 让
   `_diffrn_ambient_temperature` 落 `?`，`key_facts` 标 `temperature_K: null (placeholder
   suppressed)`；`set_experiment` 的 remove 语义要能覆盖"下游缺省注入"，
   `remove_requested_but_absent` 不应静默通过。

2. **`add_hydrogens` 的 `warnings` 与 `skipped` 互相矛盾，且含花括号笔误。**
   证据：纯工具臂 T+26.63，`n_h_added: 6 / n_h_removed: 6`、`kinds: {aromatic_CH: 6}`、
   `skipped` 含 O003–O008，同时 6 条 warning 声称 "O003…O008: metal-coordinated O protonated
   (include_metal_bonded) - verify against the difference map"；
   消息文本 `force_kind={'O005': 'OH'}}`。
   建议：warning 只对**实际加了 H** 的载体发；`include_metal_bonded=true` 但被端基规则跳过时
   改成一条明确的 informational（"6 个金属端基 O 未加 H：需 force_kind 显式指定，或先看差图"）；
   修掉多余的 `}`。

3. **tools_only 档位下工具文案仍推荐读不到的技能卡。**
   证据：纯工具臂工具返回 6 处 `read_skill` 指针（`audit_reflection_data` T+4.05、
   `audit_heavy_sites` T+13.40、`audit_element_assignment` T+19.03、`solvent_mask` ×3、
   `write_outputs` T+35.84）；agent T+4.25 / T+4.36 两次探测 `read_skill` 均返回空输出。
   建议：`knowledge_mode='tools_only'` 时按注册表剥掉返回文本里的 `read_skill …` 指针
   （或整段判读文案），否则消融不纯，且让 agent 白跑探测。

### P1

4. **`solvent_mask` 缺 `max_cycles` 上界与成本预警。**
   证据：纯工具臂 T+31.80 `max_cycles=5000` 跑 239.6 s 后仍以"空腔被丢弃"失败；
   T+27.80 推理"max cycles set to 5000, which might take about four minutes"（它知道会慢）。
   建议：给 `max_cycles` 上限（例如 1500）并在超限时返回"BYPASS 不收敛不是 cycle 不够，
   看 `mask_diagnosis` / 补全骨架"；返回里附按已跑 cycle 估算的预计时间。
   （与 org lane 的 `solve_charge_flipping` 无预算问题同源。）

5. **`solvent_mask` 应自带带/不带掩膜的 ΔR1 对照，而不是靠 agent 自觉。**
   证据：`mask_decision_note` 已明写"whether to KEEP the mask is decided by the refinement…
   compare R1/wR2 and the residual map against the unmasked node"，但纯工具臂没做，
   SUMMARY 只能写"显著改善"；全栈臂做了（`R1 0.2006 → 0.0870`）并写进 SUMMARY。
   建议：`solvent_mask` 返回里直接给出同模型 unmasked 基线节点与 ΔR1/Δ残差
   （或返回一个 `compare_with` 节点 id 供一步调用）。

6. **`run_shelxt` 应在 `n_phase_sets` 被显式加大时当场劝阻。**
   证据：纯工具臂两次传 300 → `per_try_s` 6.8 / 9.0 vs 全栈臂默认 2.7；
   job1 `total_s 462.0` 中 `sg_search_s 285.6`。
   建议：传入 `n_phase_sets` 时返回一行"−m300 会把每个 try 从 ~2.7 s 拉到 ~7 s×16–20 try；
   除非上一次因相位失败（而非超时），建议不传"；`all_space_groups=true` 且会话已确认群时
   提示 `space_group=` 可把 `sg_search_s` 从数百秒降到数秒。

7. **`ingest_vendor_data(ins=<file>)` 会把厂商 LATT/SYMM 变成 working symmetry。**
   证据：纯工具臂 `ins='start.ins'` → `symmetry.confirmed: false`，但
   `estimate_resolution.merge_laue_source = "working symmetry"`（P6/mmm）；
   全栈臂 `ins='-'` → `merge_laue_source = "lattice metric (working symmetry is
   triclinic/undecided)"`。
   建议：`ins=<file>` 时也把 LATT/SYMM 降级为 `ins_guess`（与 `ins='-'` 一致），
   只取胞与波长；或在 `screen_space_groups` / `estimate_resolution` 返回里显式标注
   "本次合并所用劳厄类来自未验证的厂商声明"。

8. **`audit_heavy_sites` / `element_scan` 的候选集应主动提示波长附近有边的元素与常见客体重原子。**
   证据：两臂候选集都不含任何卤素以外的客体重原子（tools I/Zr/Zn/Cu/Fe/Co/Ni；
   full I/Zr/Hf/Zn/Cu/Fe/Cd），参考里的孔道客体含 `Br6` occ 0.125；
   工具的 `anomalous.strong_fp` 已能列出 `["Bi","Mo","Nb","Pb","U","Y","Zr"]`。
   建议：`audit_heavy_sites` 给出 `suggested_candidates`（λ 处 |f'|>2 的元素 + 与观测
   z_eff 相容的元素），并对**孔道内**的高残差位点单独提示"用 probe_site 试重原子客体"。

9. **`mask_obligations` 指向的客体电子数检验没有强制点。**
   证据：两臂 `write_outputs` 都返回同一条 `mask_obligations`（含
   `read_skill mof-guest-evidence-rule`），但两臂都没调
   `integrate_difference_density` / `audit_guest_evidence`，也没读那张卡；
   参考的 1/8 占有溴芳客体因此两臂全漏。
   建议：掩膜交付时把"掩膜前区域电子数积分"变成 `write_outputs` 的硬项之一
   （未做则自动在 `unresolved` 里落一条），而不只是一句叙述义务。

### P2

10. **技能库缺"吸收边 / 异常散射与元素指认"卡。**
    证据：全栈臂 T+6.34 `list_skills('Zr absorption edge element assignment')` →
    `n_skills: 0`，`near_misses_per_word` 里 `Zr` 与 `edge` 各 0 命中。
    建议：把模板那段（"λ 靠近吸收边时该元素看起来轻一档 / DISP 卡 / 两引擎 R 不互比"）
    固化成一张卡，`tools: [audit_heavy_sites, element_scan, run_shelxl, set_experiment]`。

11. **`campaign_analysis` 把合法轮询算成 spin / churn。**
    证据：纯工具臂 `spin` 报 `run_shelxt {job_status: job_20260903_155917} ×7`；
    `arg_churn` 报 `run_shelxt 5 calls / 3 distinct args`。
    建议：`find_spin` / `find_arg_churn` 对含 `job_status=` / `from_job=` 的调用豁免，
    并把"轮询次数 × 间隔"单列成一个 waiting 指标。

12. **等待 SHELXT 缺一个受支持的等待方式。**
    证据：纯工具臂 10 次 `shell_command("Start-Sleep -Seconds 35..55")`（每次起一个
    PowerShell 进程，非 auto 档位会进审批队列）；全栈臂 2 次 `setTimeout`。
    建议：`run_shelxt(job_status=…)` 支持 `wait_s=<秒>`（服务端阻塞等待并返回最新
    stage / tries / best_cfom），把"轮询 + 睡觉"收回工具内。

13. **`import_frames` 的报错可以直接给出改道。**
    证据：纯工具臂 T+0.68 `no scan frames recognised … No recognisable diffraction frames
    found.` → 随后花 1 次 exec 探测 ingest 类工具名。
    建议：报错里附上目录扫描结果（"发现 crystal.hkl (HKLF4-like) 与 start.ins：
    厂商产物路线请用 ingest_vendor_data(list_candidates=true)"）。

---

*核读依据：`hex-tools-r1/logs/rollout.jsonl`（674 条记录，195 次工具调用，49 段推理）、
`hex-full-r1/logs/rollout.jsonl`（674 条，194 次，51 段）、两格 `grade.json` / `verdict.json` /
`state.json`、两个交付目录的 `final.cif` / `final.res` / `SUMMARY.md` / `VALIDATION.md`、
参考 `H:/CrystalPilotData/refs/nu1000_034a1_manual.cif`；机械指标由
`crystalpilot.benchmark.campaign_analysis.analyse_case` 计算。*
