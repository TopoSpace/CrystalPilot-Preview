# 第三轮 R5 复盘：师兄功能正确性与范围自适应（2026-09-06）

> 对应计划 `docs/PLAN-2026-09-05-round3.md` §3 R5。本轮没有跑新的解单晶格（计划里 R5 的真实数据项就是"cage 项目分析页 + UI 截图，只读"）；所有核对都在已有真实项目与公开已知答案晶体上做。API 在本轮全程可用，没有触发"暂不可用"预案。

## 1. 目标对照

| 计划项 | 结果 | 提交 |
|---|---|---|
| A 对称闭合环真正计算并进入 π–π / C–H···π 表 | ✅ `chem/interactions.py` 按对称算符把环建出来；Zn2_dhtp 的 π–π 表从空变成与 PLATON 逐行一致（12 行比对） | `5ce7154` |
| B 有限片段闭包 / 长满（Olex2 `grow`） | ✅ `refine/scene.py::_grow_all`：直到同一片段里同一原子的同一旋转部分重复为止；周期网只长一个周期并画"帽"原子；查看器"长满"开关 + "周期截断 / 原子预算截断"药丸 | `f27453d` |
| C 孔道统计标"每胞"、两个电子数口径 | ✅ `analyze_packing.pores.electron_count_basis`：本节点重算 vs 精修掩膜快照，同为每胞，差 >20 % 时明说"以精修掩膜快照为准"；分析页两行数字并列 | `e2de771` |
| D 方向性 PLD（沿 a / b / c） | ✅ 每个贯通孔带 `pld_along {a,b,c}`（不沿该轴贯通 = null），同一渗流二分按方向约束；15 s 预算超出则给说明；分析页孔行"沿 a/b/c x/y/z Å"；旧缓存靠 `VOIDS_CACHE_V=6` 失效 | `e2de771`、`89b5ea1` |
| E 互穿 / 互锁：环穿越判定 | ✅ `chem/threading.py`：收缩图最短环 = 窗口，另一网的原子级键穿过窗口扇面即穿越；`interpenetrated` / `interlocked_1d` 从 null 变成 true / false / 未判定（带原因）；双重互穿 MOF-5 与平行层反例是已知答案 | `373de4f` |
| F 已知答案扩充：阴离子–π、π–π ≥15 行、螺旋真实晶体 | ✅ COD 2232050（阴离子–π + π–π）、COD 4115425（6₁ 螺旋链）；π–π 比对行数：Zn2_dhtp 12 + 原有 5 + 新 1 = 18（另 8 行涉及 8 元并环仍豁免，见 §3） | `a5e71e5` |
| 纯 CIF 项目补 PLD | ✅（R5-D 顺带）几何孔道路径 `_build_geometric_void_ccp4` 同样带全路径 PLD 与沿轴 PLD | `e2de771` |
| G（可选）Mode Grow、晶胞框图层、逐图层范围 | ❌ 未做，留到下一轮（见 §5） | — |

## 2. 做法要点（都是通用规则，不写测试晶体常数）

### 2.1 对称闭合环（R5-A）
- 原先 `find_rings` 按构造拒绝"经非恒等算符闭合"的环（防止把一维链的晶格回路当成环），结果反演中心上的苯环（ASU 只有 3 个碳）连同它的全部 π–π 行静默消失，09-05 的验证只做到"点名缺失"。
- 现在 `_rings_through_symmetry` 记录闭合路径、每步算符与闭合算符，`_ring_defs` 用 闭合算符^k 把整环铺出来（阶 n 有限、路径长 × n 落在 5/6 元），几何走同一个 `_ring_geometry`；环行带 `through_symmetry {op, order, asu_atoms}`，普查条目带 `built` / `aromatic`；`ring_note` 改成"本结构有 N 个这种环，已建出并参与每一条 π–π / C–H···π"。
- 已知答案：Zn2_dhtp 的 PLATON 窗口内 20 行 π–π 中 12 行涉及这种环，现逐行比对通过（Cg···Cg、两侧垂距 ≤0.01 Å，夹角 ≤0.5°，滑移 ≤0.01 Å）；其余 8 行涉及 `find_rings` 不搜的 8 元并环，仍按引擎自述判据豁免并写进 `MIN_PIPI_COMPARED` 的注释。

### 2.2 长满（R5-B）
- Olex2 的 `grow` 语义："继续长，直到会产生一个此前已用过的对称元素"。实现：每个片段一个并查集；给原子 j 加新像时，若片段里已经有 j 的一个像且旋转部分相同，则视为晶格重复，只画一次作为"帽"（cap），不再从它长出去。0-D 分子（跨胞边界、穿反演中心、穿三次轴）长到完整为止；链 / 层 / 网长一个周期即停，`grow_all {periodic_edges, caps, n_added, budget_hit, complete}` 如实回报。
- 单原子永不与自己的晶格像成键（一个原子的"网"画不出键），所以夹具用两原子 bcc 网。
- 实机：DBU 盐 n0028 长满 = 完整 57 原子；Zr-MOF n0109 长满 = 647 原子、93 个周期帽、`complete=false`（药丸"周期截断"）；Zr6 笼项目见 §4 截图。

### 2.3 两个电子数口径（R5-C）
- 现象：R4 复跑里 `solvent_mask` 记的 591.6 e/胞 与 `analyze_packing` 重算的 1193.2 e/胞 并列出现，读者无从判断哪个是哪个。两者都是 smtbx 掩膜的 `f_000_s`，单位都是每胞；差别在**模型与掩膜循环**：快照是精修当时（可能在祖先节点）进入 Fc 的那份掩膜，重算是在当前节点模型上用记录参数重新跑的 BYPASS。
- 输出：`pores.electron_count_basis = {per: "cell", recomputed_on_node, params_source, recomputed_total_e, refinement_mask_snapshot{...}, relative_difference, agree, note}`；阅读句同时写两个数并标 e/胞，差 >20 % 时写"计量以精修掩膜快照为准，重算值只作对照"。分析页在参数来源行上方加一行"重算掩膜电子 1193.2 e/胞 · 精修掩膜快照 591.6 e/胞 ⚠"。
- ~~**没有解释的部分**：n0109 上两者恰好差 2.02 倍。这次只把口径写清，没有追这个倍数的来源。~~ → **2026-09-06 05:00 已追到并修复（§7 补记）**：重算路径重建模型时丢了反常散射项（数据在 Zr K 吸收边上，f′(Zr) = −9.04 e），既不是客体原子的增删，也不是循环数。

### 2.4 方向性 PLD（R5-D）
- `chem/pores.pore_limiting_diameter(..., directions=[d])` 早已支持方向约束，只是产品没有接口。`refine/scene.py::_pld_along_axes` 对维度 ≥1 的孔按 a、b、c 各跑一次二分；全路径 PLD 若已超 15 s 预算则跳过并写 `pld_along_note`。
- 实机 Zr-MOF n0109：全路径 PLD 8.196 Å（逃逸方向 [0,0,1]），沿 a / b 6.185 Å，沿 c 8.196 Å——同一个孔"沿 c 宽、沿 a/b 窄"，单个 PLD 表达不了。三次方向二分各约 1.6 s（135×135×60 网格）。

### 2.5 环穿越互穿判定（R5-E）
- 收缩规则与简化网相同（金属簇–连接子；无金属时分支点作单点，保留带平移的自环边）；每个角取最小环（BFS 在提升图 (节点, 平移) 上），模平移去重，Franzblau 最短路环过滤；窗口按质心扇面三角化，另一网的键（直线段）用 Möller–Trumbore 判穿越；一对网只要有一个窗口被穿即互穿（维度 ≥2）或机械互锁（一维链）。
- 判定状态：`tested` / `inconclusive`（预算 20 s 用尽，`interpenetrated` 保持 null 并说明）/ `not_testable`（链的收缩图没有环）/ `not_applicable`（单网）。
- 已知答案：MOF-5 + 平移拷贝 → `interpenetrated=True`（每侧 12 个六元窗口被穿）；反演相关的双重互穿 MOF-5 → True；平行层 → False（"不互穿"）；螺旋链对 → `interlocked_1d=None, not_testable`；pcu 3 个四元窗口、dia 12 个六元窗口。真实 Zr-MOF n0109 单网 4.5 s。

### 2.6 已知答案扩充（R5-F）
- **阴离子–π**：COD 2232050（Acta E67 o2762，三嗪鎓四氟硼酸盐）。作者摘要给 Cg1···F4ⁱ 3.178(3) Å、Cg1···F2ⁱ 3.654(3) Å（(i) 1−x, 2−y, 1−z）与环–反演像堆积 Cg···Cg 3.3361(12) Å、面间距 3.333 Å、滑移角 2.46°。引擎：阴离子 BF₄⁻ 被 `_FRAGMENT_SIGNATURES` 识别，行的算符正是 (i)，B···Cg 3.720 Å、偏移 0.70 Å；测试在同一模型同一算符下重量 F4···Cg = 3.178、F2···Cg = 3.654（±0.01）；π–π 行 d_cc 3.3362、垂距 3.3331、滑移角 2.466°。5 条沉积氢键行全部复现。
- **螺旋链**：COD 4115425（JACS 123, 743，Pt→Ag 金属–金属键螺旋链，P6₁，c = 41.608 Å）。引擎：1 个一维片段，`screw 6_1`、右手、螺距 = 轴重复 = 41.608 Å、`racemic=False`。诚实说明：ACS 全文页对本机 403，摘要里的螺距数字未能核对，测试断言的是空间群 + 链方向的推论。
- **π–π 行数**：PLATON 交叉比对现在必须"比对"而不是"豁免"至少 12 行（Zn2_dhtp）+ 1 行（新结构）；全套比对行 18。

## 3. 真实结构上的数字（只读）

| 结构 | 项 | 数字 |
|---|---|---|
| Zr-MOF r4-mof n0109（P6/mmm） | 孔 V1 体积 / 维度 | 16996.1 Å³，3-D |
| 同上 | PLD 全路径 / 沿 a / 沿 b / 沿 c | 8.196 / 6.185 / 6.185 / 8.196 Å（±0.3 Å 网格步长） |
| 同上 | 残余电子（重算 / 精修快照） | 修复前 1193.2 / 591.6 e/胞（2.02 倍）；修复后 n0109 419.3（收敛 14 轮）/ 591.6（n0108 的快照），n0108 593.7 / 591.6（§7） |
| 同上 | 拓扑 | 单网，互穿 not_applicable，4.5 s |
| 同上 | 长满 | 647 原子、93 周期帽、未完整 |
| DBU 盐 n0028 | 长满 | 完整，57 原子 |
| Zn2_dhtp（public） | PLATON π–π 窗口内 20 行 | 12 行逐行一致；8 行为 8 元并环豁免 |
| COD 2232050 | 阴离子–π / π–π / 氢键 | 见 §2.6；5/5 氢键行复现 |
| COD 4115425 | 螺旋 | 6₁ 右手，螺距 41.608 Å |

## 4. 证据

- 单元 / 已知答案测试（本轮新增或改动）：`tests/test_interactions.py`（26，含反演中心苯环建 6 原子 + 与晶格像堆积、三次轴苯环）、`tests/test_scene_grow_all.py`（10）、`tests/test_topology.py`（+预算耗尽为 null、收缩图窗口计数）、`tests/test_known_answers_topology.py`（互穿真值 + 螺旋已知答案）、`tests/test_pld_along.py`（4）、`tests/test_analyze_packing.py`（+2：口径纯函数四种情形、产物携带）、`tests/test_upgrade_structure_document.py`（几何孔道路径带沿轴 PLD）、`tests/test_known_answers_interactions.py`（+阴离子–π 已知答案、最少比对行数）。
- 相关套件本轮运行：voids / packing / scene / structure-document 120 passed；已知答案（interactions）80 passed / 22 skipped（PLATON 交叉 slow 项按环境跳过）后加新例 11 passed；PLATON π–π Zn2_dhtp 单测 passed。
- vitest 315（35 文件）；tsc 干净；`npm run build` 后受管重启，health 200。
- Playwright 证据轮 **r3-r5**（`workdir/ui-evidence/r3-r5/`）：`r2b-layout.pw.ts` 6 passed（Zr6 笼项目 pe8f898bd，189 节点）；新增 `e2e/r5-analysis.pw.ts`（长满 + 分析页孔道块）在 r4-mof 与笼项目上各 2 passed（浅 / 深）；截图 `r4mof-grow-all-*`、`r4mof-analysis-pores-*`、`r4mof-analysis-topology-*`、`cage-*`。
- 全量 pytest：见 `docs/UI-EVIDENCE-2026-09.md` 第三轮 R5 节（`workdir/pytest-full-r5.log`）。

## 5. 没做 / 边界

- **R5-G 未做**：Mode Grow（短接触 / vdW / 选中原子的对称像候选键）、晶胞框作为可关图层、`scene.range.layers` 逐图层 requested/drawn（现有 tiles 药丸只披露整体）。
- 沿轴 PLD 只有 a / b / c 三个方向；非轴向通道（如 [1,1,0]）仍只在 `pld_directions` 里出现，没有对应数字。
- 阴离子–π 的量法是阴离子质心到环心（弱读数），不是 PLATON 的原子到环心；两者在测试里通过同一算符下的重量对上，但产品行本身不带原子级距离。
- 螺旋已知答案是对称推论（P6₁ + 单条链沿 c），不是论文引用的数字。
- 互穿只做了环穿越，没有 Gauss 链接数；棒状 SBU 收缩仍报 inconclusive；20 s 预算内未完成的判定保持 null。
- ~~两个电子数口径 2.02 倍的来源没有追。~~ → 已追到并修复（§7）。
- `find_rings` 仍只搜 5/6 元环：8 元并环的 π–π 行继续豁免（Zn2_dhtp 8 行）。

## 6. 下一步

R6（提问卡、引用芯片、插话回执、知识模式 UI）按计划进行；R5-G 作为 R6 之后的候选（"2.02 倍"已在 §7 解决）。

## 7. 补记（2026-09-06 05:20）：2.02 倍的来源与修复

**复现**（仓库外脚本 `C:\tmp\claude\mask_repro*.py`，在 `r4-mof` 的 n0108 / n0109 `model.res` 上重跑掩膜）：

| 试验 | 结果 |
|---|---|
| smtbx 自己的循环（重算原路径）| n0109 1193.2 e（9 s 收敛）；n0108 1368.9 e |
| `BypassMask`（工具路径，同参数）| n0109 起步 1667 → 234 → 回升，第 12 轮被发散护栏截停在 408；去掉护栏 163 轮收敛到 1193.2 - **两种循环收敛点相同，循环实现不是原因** |
| 数据按 `SHEL 999 1.000` 截到 1.0 Å | 起步 894.8，仍发散，不是数据集 |
| 流填体积 | 重算 16984.6 Å³ vs 记录 16985.3，模型几何一致，不是模型 |
| **给重建的模型补上 `model.res` 里 DISP 卡的 f′/f″** | n0108 起步 **2371.2 → 收敛 593.7 e**（137 轮）；记录是 2372.2 → 591.6（98 轮）。**命中** |

**原因**：`RefineProject._build_session` 从 `model.res` 重建模型时只设了散射因子表 `it1992`，没有设反常散射项；进程内 `refine` 引擎（`tools/refinement_tools.py`）会 `set_inelastic_form_factors(λ, "sasaki")`。这批 NU-1000 数据的波长 0.68883 Å 正落在 **Zr K 吸收边**（17.998 keV）上，Sasaki 表给 f′(Zr) = −9.041 e、f″ = 2.771 e，每个 Zr 少算 9 个电子的散射，差值图在孔里多出来的密度就是那"多出来的一倍"。影响范围不止查看器重算：**每次 checkout / 分支 / 新开项目重建会话都丢项**，直到下一次进程内 `refine` 才补回；SHELXL 作业不受影响（DISP 卡由 writer 独立生成）。pa1 hex-l2-r1 n0024 那个"17,490 Å³ 通道首轮密度为负被 BYPASS 丢弃"的老故事同样是它：带上项后同一调用得到 1163.5 e 的正常掩膜（`tests/test_mask_bypass.py::test_hex_l2_r1_node_n0024_masks_once_the_anomalous_terms_are_back`），不带项仍按原样失败并给出诊断（另一条回归保留）。

**修复**（通用，不针对 Zr）：
- `io/shelx_writer.apply_anomalous_terms(xs, wavelength)`（Sasaki，与精修引擎同一处）+ `anomalous_terms_of(xs)`；`_build_session` 两个分支、精修引擎、重原子图（`tools_heavysites`）都改走它；电子波长（< 0.1 Å）与无波长时不设。
- **收口点**：`SolveSession.model` 改为属性，赋值时按数据集波长补项，`run_shelxl(adopt)`、改空间群、导入、拆分、`select()` 拷贝等 14 处把新结构放进会话的路径（此前 SHELXL adopt 之后的会话模型同样没有项，直到下一次进程内 refine）一次全部覆盖，未来的新路径也不用记得调用（`tests/test_anomalous_terms.py::test_session_model_setter_applies_the_dataset_terms`，`test_shelxl_tools` 的 adopt 用例断言 adopt 后带项）。
- `solvent_mask` 摘要与节点 `mask.info` 记 `anomalous_terms`（元素 → [f′, f″]）。
- 查看器重算改用 `BypassMask`，`voids.json` 记 `bypass{converged, diverged, n_cycles, kept_cycle, f000s_first/last/min/max}` 与 `anomalous_terms`（`VOIDS_CACHE_V=7`，旧产物自动重建）；`analyze_packing.pores` 透传两块，`electron_count_basis` 加 `recomputed_converged / recomputed_cycles / anomalous_terms`，重算未收敛时阅读句写"该值不是定值，以精修掩膜快照为准"；分析页同一行加"重算未收敛"提示（`data-recount` 属性）。

**修复后实测**（服务器重启后重跑分析作业）：

| 节点 | 重算 | 精修掩膜快照 | 读法 |
|---|---|---|---|
| n0108（solvent_mask 节点） | 593.7 e/胞，收敛 137 轮（2371.3 起） | 591.6 | 一致（0.4 %） |
| n0109（其后 SHELXL adopt_wght） | 419.3 e/胞，收敛 14 轮（2321.3 起） | 591.6（n0108 上算的） | 差 29 %：这次是真的模型不同，按规则以快照为准 |

**顺带修的第二处**：`BypassMask` 的发散护栏（连续 8 轮上升且涨幅 > 20 %）会把"先下冲再回升到不动点"的序列误判为发散（无项模型上 n0108 第 14 轮停在 602.8，去掉护栏 163 轮收敛到 1368.9）。护栏抽成 `runaway_series(tr, window, growth)` 并加第三个条件：**序列必须已高于自己的首轮估计**：首轮值是原始差值密度在孔内的积分，BYPASS 不动点总在它之下，真正的失控（pa1 hex-l3-r3 1636 → 7479）一定越过它，回升序列不会。用 n0108 的那 14 个数与失控形状各写一条测试。

**证据**：`tests/test_anomalous_terms.py`（3：Sasaki 值与引擎一致、重建/checkout 带项、重算记项与序列）、`tests/test_mask_bypass.py`（hex n0024 两条）、`tests/test_analyze_packing.py`（未收敛读法）、`tests/test_scene.py`；Playwright 证据轮 `r3-anom`（`e2e/r5-analysis.pw.ts` 于 r4-mof，2 passed，`anom-analysis-pores-light.png`："重算掩膜电子 419.3 e/胞 · 精修掩膜快照 591.6 e/胞 ⚠"）；全量 pytest 2509 passed / 26 skipped / 0 failed（10:48）。
