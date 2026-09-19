# 第三轮 R3 复盘（2026-09-05/06）：工具面 P0：状态与诚实

> 计划：`docs/PLAN-2026-09-05-round3.md` §3 R3 与 §9 工作包表（WP1 / WP2 / WP3 / WP4 / WP6 / WP8 + T-j / T-k）。tag：`r3-r2-done` → `r3-r3-done`。
> 提交：`76e3728`（WP1 分层结果信封 + WP6 诊断隔离 + T-k 掩膜键名）、`4be3b40`（WP8 schema 边界守卫 + 知识卡/掩膜文案改条件句 + T-j 配位客体措辞）、`4db0928`（WP3 PART 生命周期 + 约束预检）、`bd6a3ba`（WP4 客体证据记账）、`8fd59a2`（WP2 有效模型状态）、本文档提交。
> 证据：`tests/test_result_envelope.py`、`tests/test_schema_bounds.py`、`tests/test_part_lifecycle.py`、`tests/test_guest_evidence.py`、`tests/test_effective_state.py`、`tests/test_probe_site.py::TestLedgerIsolation`；实机一格 DBU 盐 `H:\CrystalPilot-campaigns\r3\r3-dbu`（事件镜像 `workdir/live-demos/r3-dbu-20260906-0014/`）；UI 证据 `workdir/ui-evidence/r3-r3/`。

取证报告（`workdir/live-demos/demo-20260905-1503/forensics-20260905-1841/`）里"成功返回藏着错误肯定"的每一条，本轮都落成了结构化字段 + 测试：工具"跑了"与"发现了什么"分开说；PART 随原子走；客体电子数的分母写明白；作业指令卡随节点保存；诊断删除不再撞真原子保护；运行时边界写进 schema；阈值改成条件句。

## 一、修好了什么

### WP1 分层结果信封（`76e3728`）

| 项 | 做法 |
|---|---|
| 信封 | `tools/base.py::invoke` 给每个结果的 `summary["tool_status"]` 填 `execution`（ran / failed / timeout / cancelled）、`scientific_outcome`（{verdict: supports / inconclusive / against, reasons, measured_by} 或 null）、`state_changed`（{changed, node_before, node_after, revision_after}，由 `project.invoke_tool` 前后节点填）、`no_change`（{value, reason}，读工具的 `no_state_change` / `no_change_reason`）、`applicability[]`、`artifact_index{}`。键名用 `tool_status` 而不是 `status` - `status` 已被 write_outputs / 作业工具占用。旧的 `ok / summary / error` 一字不动。 |
| 预算循环 | 部分结果（`summary.timeout` 字符串 / `cancelled: True`）映射到 timeout / cancelled；`BudgetStop(stage, elapsed_s, budget_s)` 继承 `BudgetExceeded`。 |
| 先接的工具 | `solvent_mask`：`execution=ran` 与 `scientific_outcome`（未收敛 = inconclusive，带 `electron_count_confidence`）分开；`fit_fragment`：零新增 → `no_change` + inconclusive；`run_shelxl`：与进程内引擎的对账写成 verdict（supports / inconclusive / against）；`audit_guest_evidence`（WP4）：三检验的读数写成 verdict。 |
| UI | `resultTail.ts` 把 `tool_status` 列入非指标容器（不会被误读成 R1/节点）；`toolCards.tsx::envelopeChips` 在每行最前面放 无变化 / 未定论 / 证据相反 / 超时 · 部分结果 / 已取消 芯片（`toolCards.envelope.test.ts`）。 |

### WP6 诊断隔离（`76e3728`）

`probe_site` 的诊断删除带 `_diagnostic: True` + `_diagnostic_reason`（下划线键绕过未知参数检查）；`edit_atoms._ledger_guard` 遇到它不再拒绝、也不写处置，只在幽灵账本上记 `diagnostic_touches`（哪次试验重看了受保护原子）。主线上的 real 判决照旧保护：手动删除仍需 `acknowledge_real`（`tests/test_probe_site.py::TestLedgerIsolation`）。

### T-k 掩膜块（`76e3728`）

`situation_report` 原来读根本没人写的 `mask_meta`，现状报告的掩膜块永远只有 `{"active": true}`；现在读 `solvent_mask_info`（体积 / 电子数 / 收敛状态），数据置换时同步清掉（`tests/test_result_envelope.py::TestMaskBlock`）。

### WP8 边界守卫与措辞（`4be3b40`）

| 项 | 做法 |
|---|---|
| 守卫 | `tests/test_schema_bounds.py` 扫每个注册工具 `run()` 里的 `if not LO <= x <= HI` 拒绝惯用法，追到 `params.get("name")`，断言 schema 声明了同样的 minimum / maximum；参数摘要行显示 `number[0.5..6]`。首批补齐：`integrate_difference_density.radius_A`、`solvent_mask.resolution_factor`、`set_weights.a/b`、`set_resolution_limit.d_min`、`set_z.z`、`audit_heavy_sites.radius_A`、`set_twin.basf`。 |
| 措辞 | `mof-guest-evidence-rule` 知识卡：占有率崩塌检验改成"按工作占有率假设与数据分辨率读、逐原子看 per_atom 表"，不再有裸百分比阈值；`negative_density_diagnosis` 尾句从"不得交付无掩膜"改成以"是否已有收敛掩膜可退"为条件的陈述，物理句保留。 |
| T-j | `analyze_packing` 在配位客体并入宿主片段时写"按宿主规则（…）没有单列出客体片段；与骨架配位/共价相连的客体已并入宿主片段，请到配位环境或原子表按标签核对"，不再说"没有客体"。 |

### WP3 PART 生命周期 + 约束预检（`4db0928`）

| 项 | 做法 |
|---|---|
| 删除随走 | 新模块 `refine/parts.py`：`edit_atoms` 删除与 `model_disorder(undo)` 共用一个策略，`parts_extra` 清掉该标签；无序组成员记录删掉，组空了就丢弃并把 FVAR 重编成连续 2..n（origins 跟着改号）；每条提到被删原子的分裂记录标 `stale` + 原因。之前同名重加的原子会继承旧 PART、undo 会"还原"一个已经不是它的原子；现在 undo 干净拒绝并指向分裂前节点。 |
| PART 显式 | `edit_atoms` 新动作 `set_part` / `clear_part`（整数 `part`，0 = 清除，负数 = 不与对称等价成键）；组成员只改成员记录，散原子进出 `parts_extra`；写 `kind: "part_edit"` 的 origin，`model_disorder(undo=<label>)` 按原子 LIFO 精确还原。 |
| 预检 | `restraints.preflight()`：请求 vs 实际施加，进程内引擎能建的项、不能表达的项（EADP/SAME 这类不是限制）、以及 DFIX / DANG / SADI / FLAT 跨不同非零 PART 的项（SHELXL 不施加，`would_be_ignored_by_shelxl`；只警告不拒绝，因为对 SHELXL 这条规则的推断未经其手册逐字核实，错了也只多一行）。`set_restraints` 与 `run_shelxl` 写 INS 前都跑并附 `restraints_preflight` + `applicability`；新只读工具 `preflight_restraints`（第 71 个工具：AGENTS 一行 + UI 卡 + READ_ONLY）。 |

### WP4 客体证据记账（`bd6a3ba`）

| 项 | 做法 |
|---|---|
| 分母带标签 | `accounting.per_atom`（Z、占有率、多重度、`electrons_at_site` = Z×occ 一个实例、`electrons_per_cell` = ×多重度）与 `denominators`：working_occupancy / full_occupancy_model / full_occupancy_formula / formula_at_working_occupancy，每个带 `meaning`。cctbx 的 occupancy 是化学占有率（位对称因子在 weight 里），核实过：反演中心上的 Cl occ 1.0 → 每胞 1 个。 |
| 检验 1 | `ratio_by_denominator` 全表 + 判词只读**工作假设**（有分子式时 = 分子式 × 工作占有率）；满占分子式的比值另写一句"这是模型没有主张的说法"。取证里 0.2 占有率客体对满占分子式读成 against 的错误由此消失。 |
| 检验 2 | 逐原子表 `{label, occ_start, occ_refined, ratio, at_bound, reading}`：全部 holds → supports；全部 collapses → against；穿 0 / 超 1 钉边界 → inconclusive；一组两栏 → inconclusive 并逐原子点名；`refined_mean` 仍报但不判。 |
| 检验 3 | 报 `engine / n_free_params / n_reflections / d_min / cycles_done / terminated_by / npd_after`；0 个循环永不 supports（inconclusive）；ADP 撤限制后非正定计入 WARNS。 |
| 其他 | `conditioned_by_prior`（触及客体的限制种类、共享自由变量、骑乘 H）；`scientific_outcome`：有 against 即 against，≥2 项 supports 才 supports，其余 inconclusive。 |

### WP2 有效模型状态（`8fd59a2`）

| 项 | 做法 |
|---|---|
| 状态 | `run_shelxl(extra_cards=…)` 采纳成功后，卡片成为 `flags.effective_cards`（含来源作业名）；`node.json` 加 `schema: 2` 与 `effective_state`（cards / data_cards / weights / fvars / parts / h_treatment / twin / mask / source）；`serialization_extras` 把卡片写进 `model.res`（final.res 就是这份文本）。 |
| 随走 | checkout / resume 还原；后续每个 SHELXL / olex2 作业自动带入（先按当前模型重新过卡片门，失效的卡按名拒绝作业并指出 `replace_cards=true`）；再传同一张卡不重复也不报错；`mode=check` 用但不持久化；`replace_cards=true` 换掉整套；删原子同命修剪（`cards_pruned`），重命名跟着改；导入的 .res 里的 EADP/EXYZ/SAME/SUMP 作为有效卡带入而不是"kept as text"（其实是丢弃）。 |
| 交付 | `write_outputs` 把 final.res 与配对作业 `job.ins` 的指令卡比对：缺约束卡 → `restartable: false` + 一致性问题 + 中文告诫；只缺测量卡（HTAB/RTAB/MPLA/CONF）→ 可重启但 CIF 测量表不可复现，如实写；`_job_match_legs` 加信息腿 `constraint_cards`（不否决配对：老节点没有这层）；评分器报告级 `restartable`。 |

## 二、验证了什么

### 自动测试

| 套件 | 结果 |
|---|---|
| `tests/test_result_envelope.py`（13）、`test_schema_bounds.py`、`test_probe_site.py`、`test_mask_bypass.py`、`test_pa2_tool_fixes.py` | 绿（批次 A–C） |
| `tests/test_part_lifecycle.py`（18：删除清附属状态、同名重加不继承、组空丢弃 + FVAR 重编、stale 拒撤销、set_part/clear_part 与撤销、原子性、预检冲突与 set_restraints 报告、工具注册） | 18 passed |
| `tests/test_guest_evidence.py`（10：原 5 + 分母标签/工作假设、满占模型读 against、特殊位置多重度、0 循环 inconclusive、混合组逐原子） | 10 passed |
| `tests/test_effective_state.py`（11：采纳即状态、随后续作业与提交、check 不持久化、replace、checkout 还原、删原子修剪、失效卡拒绝、卡片读取/一致性/修剪/重命名、交付一致性点名、导入带卡） | 11 passed |
| 邻近套件（35 个文件：shelxl / node / write_outputs / deliver / finalize / disorder / grade / olex2 / h_* / ghost_* / import / project / restraint / agents_md …） | 593 passed / 1 skipped |
| vitest（全部 35 个文件） | 315 passed；tsc 干净；`npm run build` 后服务器受管重启（health 200） |
| 全量 pytest（仓库外 basetemp，`workdir/pytest-full-r3.log`） | **2425 passed / 25 skipped / 0 failed**（2026-09-06 00:27，12 min 17 s；R2 时 2368） |
| Playwright（实机 DBU 项目，证据轮 r3-r3） | `r2b-layout.pw.ts` 6 passed |

### 实机一格：DBU 盐（`orgdis_dbu`，已知答案 R1 0.0447）

启动 2026-09-06 00:14:13，线程 `01a07259-5f2e-7301-8e39-9e8fa7ca2e6a`，项目 `H:\CrystalPilot-campaigns\r3\r3-dbu`（源数据 `H:\CrystalPilotData\staging\reg1-dbu` 只读，只拷 crystal.hkl / start.ins），先验只有一句合成记录（DBU 与 3,5-二硝基苯甲酸 1:1 投料，预期 C16H20N4O6），gpt-6-astra @ xhigh，子代理关，MCP 71 个工具就绪；空闲于 00:38:16。

| 项 | 结果 |
|---|---|
| 墙钟 / 调用 | 24 min；74 次工具调用（33 种），其中 run_shelxl 9、model_disorder 5、set_restraints 4、branch 4、refine 4；无人插话 |
| 路线 | P1 冷启动 → `screen_space_groups` / `check_symmetry` 定 P2₁/n → `run_shelxt` → 元素审计与重命名 → 骑乘 H → 发现 DBU 七元环段无序：`model_disorder` 分裂 + SADI/SIMU 限制 + `run_shelxl(extra_cards=[EXYZ/EADP …, HTAB …])`；另开 `terminal-oxygen-disorder-tests` 分支试硝基氧位点分裂（R1 0.0431 但"未获可靠支持"，放弃）；`checkout` 回主线后 `assemble_asu` / `analyze_packing` / `run_olex2` / `validate_structure` / `write_outputs` / `run_checkcif` / `finalize_delivery` |
| 结果 | 29 节点 / 5 分支；交付 n0028（`dbu-disorder-complete-boundary`）：**R1 0.0445**（COD 2241572 发表值 0.0447）、wR2 0.1121、GooF 1.01、2560 反射、残差 +0.187 / −0.219 e Å⁻³；DBU 构象无序占有率 0.7132(72) / 0.2868(72)；Olex2 独立复核一致；checkCIF A7 B2 C8 G18 逐条解释；第一次 `finalize_delivery` 被门禁拒绝（阻断项未处理），第二次以 9 条显式豁免（7 条 A 级资料缺失 + 2 条限制）封为 final，agent 的结束语明写"不是问题已修复，也尚非投稿就绪" |
| 本轮字段在实机上的样子 | `tool_status` 出现在 27+ 条结果里（例：edit_atoms `state_changed n0001→n0002`）；`set_restraints` 的 `restraints_preflight`：requested 6，applied 5 × SADI + SIMU，`shelx_part_conflicts []`；`edit_atoms` 删除触发一次 `part_hygiene`；**WP2 实证**：`write_outputs` 的 `restart_cards.res_cards` = `EXYZ C13 C13B / EADP C13 C13B / EXYZ N2 N2B / EADP N2 N2B / HTAB N2 O1 / HTAB N2B O1`，与配对作业 job.ins 的约束卡一致，`restartable: true`，`coherence_issues []`，取证里"final.res 丢 EADP/SUMP 却报 agree"的那类问题在这一格上不再可能发生 |
| UI 证据 | `workdir/ui-evidence/r3-r3/`：`r2b-layout.pw.ts` 6 用例（900 / 1100 / 1440 × 浅深）在该项目上全过；我看过 `1440-light-thread.png`（状态行"空闲 · 上次回合 23:42 · 节点 n0028"，交付卡"定稿 · 豁免 9 · R1 0.0445 wR2 0.1121 GooF 1.01"，结构画布里 DBU 阳离子的两套环构象与硝基苯甲酸根）与 `1440-light-nodes.png`（5 条分支折叠，n0028 标"已交付"，n0026 标"R1 最优 0.0431"——最优 R1 落在被放弃的试验分支上，树如实显示，不替 agent 挑赢家） |
| 观察到但本轮没改 | agent 在写 SUMMARY 时先用 shell 的 apply_patch 向结果目录加文件，命令退出码 124（被沙箱/超时拒绝），随后走工具路径成功，工具面没有"写交付说明"的显式通道，agent 才去碰 shell（R4 WP7 的 `write_outputs(summary_note)` 路径要在模板里说清）；温度未记录仍以 CIF 警示句披露（既有行为） |

## 三、没做什么（如实边界）

- SHELXL 对跨 PART 约束"不施加"的规则未逐字核对手册，预检只警告不拒绝；`.lst` 里的限制计数才是最终裁判。
- 预检只覆盖 DFIX / DANG / SADI / FLAT；ADP 类（SIMU / DELU / RIGU / ISOR）跨 PART 的行为没有建模。
- `effective_state` 只在新提交的节点上有；老节点检出时没有卡（显示为空，不猜）。`_job_match_legs` 的卡片腿因此只作信息，不否决配对。
- 导入捕获只覆盖 `.res` 的 EADP / EXYZ / SAME / SUMP（读取器把 HTAB / EQIV 之类直接丢掉，没有经过 `restraint_lines`）。
- 评分器只把 `restartable` 作报告项，不进档位。
- 工具失败行的中文化（R2 留下的）没做：WP1 的信封目前只结构化了成功侧；`error` 仍是字符串。
- AGENTS 模板没有为 `tool_status` 加说明（下一轮 WP7 改模板时一起）。

## 四、复现

```bash
.venv/Scripts/python.exe -X utf8 -m pytest -q --basetemp=C:/tmp/claude/cp-pytest-tmp/r3 -p no:cacheprovider tests/test_result_envelope.py tests/test_schema_bounds.py tests/test_part_lifecycle.py tests/test_guest_evidence.py tests/test_effective_state.py tests/test_probe_site.py
```

```bash
.venv/Scripts/python.exe -X utf8 scripts/run_live.py --source H:/CrystalPilotData/staging/reg1-dbu --name r3-dbu --brief workdir/live-demos/briefs/r3-dbu.md --context workdir/live-demos/contexts/r3-dbu.json --title "R3 工具面回归 · DBU 盐（orgdis_dbu）" --structure-class salt_cocrystal --strip-placeholders --hours 1.2
```
