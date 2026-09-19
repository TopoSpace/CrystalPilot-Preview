# 前端证据记录（2026-09 第二轮）

## 2026-09-05 追加全面盘点（本轮）

完整结论见 `AUDIT-2026-09-05.md`，下一轮方案见 `PLAN-2026-09-05-upgrade.md`。

| 证据轮 | 实际数据与检查 | 结果 |
|---|---|---|
| `audit-0905-before` | reg12 Cage；1100×700、1366×768、1920×1080、深浅色、权限/结构卡/关系/分析等交互 | 初次 Edge 启动失败；三个用例完成，窄屏单项重跑通过；300px 额外 DOM 测量确认按钮/菜单越界 |
| `audit-0905-after` | 同一真实 Cage；增加 300px、13/16px 文字、选择原子并引用其真实节点/单位；全页签与 grow/超胞/孔道/关系 | **12 passed，77 张截图**，无未捕获页面错误；旧边界 reset.right=1158.4 > 1100，修复后位于面板内 |
| `audit-0905-validation-before` | 明确的**事件夹具**，只用于验证 React 生命周期与错误状态，不作科学成果证据 | 旧生产包两条都复现 React #310（空→首次结果、异步产物→结果）并保留 trace |
| `audit-0905-validation-after` | 2 条事件夹具 + 4 条真实 Cage 页面/图层用例 | **6 passed**；失败/缺报告不显示零警报；检查报告明确不随历史节点自动重算；GooF 采用统一比较逻辑 |
| `audit-0905-mof` | 真实 `H:\CrystalPilot-campaigns\ka1-hex\p92391ef8` 的 n0041；两主题、grow、2³超胞、半径、孔道、关系、简化网与分析 | 首轮 3 passed/1 timeout，浅色对应项重跑 **1 passed**；所有实际视图已完成，但首开延迟仍是待优化项 |
| `audit-0905-final` | 最终生产构建指纹、两主题×两字号侧栏、验证生命周期、项目注册就绪检查 | 捕获并修复产物轮询早于项目注册的真实404；确定性回归旧包失败后，新包 **8 passed**。失败证据保存于 `audit-0905-artifact-race` |

**不隐藏的性能边界：** MOF 冷分析耗时约 **130.08s**，其中孔道117.57s、客体7.06s、拓扑5.25s、相互作用0.20s；超过原测试90s等待，页面仍显示“正在计算分析表…”。随后缓存访问正常。`audit-0905-mof\cold-analysis.json` 与 `cold-first-open-failure\trace.zip` 保存证据；没有仅通过调大超时把它写成性能已修复。

图像均位于 `workdir\ui-evidence\<证据轮>`，保留在本机，不提交原始结构/转录或受限二进制。截图是实际应用画面，不是原型。事件夹具文件名带 `validation-event-fixture`，与真实结构截图分开。

本轮代码回滚点：`f5c250a`（侧栏/引用/可读性）、`132d95c`（验证生命周期/指标）、`27ff43d`（互穿语义与分析缓存v6）。模型/科学回放提交及真实 Astra 端到端结果详见盘点报告。

以下为此前 R0–R7 的历史证据记录，不代表本轮重跑。

---

> 约定：每轮结束追加一节。截图落在 `workdir/ui-evidence/<round>/`（`workdir/` 不入库，本文记录截图清单、所用项目、命令、观察与结论，让没有截图的人也能核对）。
> 截图由 Playwright（`ui/e2e/`，`npm run e2e`，Edge `channel: "msedge"` 无头）在**运行中的真实服务器**与**真实项目**上拍，不是组件示例页。
> 前置守卫：`ui/e2e/health.pw.ts` 断言 `/api/health` 的 `ui_build.stale === false`，即服务端正在提供的 `ui/dist` 比所有 `ui/src` 源文件都新（防止再次出现"改了源码、看的却是旧构建"，缺陷 D1）。

---

## R0 基线（2026-09-04）

### 环境

| 项 | 值 |
|---|---|
| 服务器 | `workdir/restart_server_r13.ps1` 重启；新监听 PID 44412（旧树 40704→11228 已按父链核实后杀）|
| 构建 | `cd ui && npm run build`（tsc → vite → `scripts/stamp.mjs` 写 `dist/build.json`）|
| `/api/health.ui_build` | `git_head_at_build 92ba1099b067`，`ui_dirty_at_build true`（R0 的前端改动当时尚未提交），`stale false`，`head_mismatch false` |
| 评测命令 | `cd ui && CP_EVIDENCE_ROUND=r0 npm run e2e` |
| 目标项目 | 未设 `CP_E2E_PROJECT`，按 `helpers.pickTarget` 取 `/api/projects/status` 第一个有节点的项目：`peeb65cea`（reg8-nm，线程 `campaign:reg8-nm:nm-full-r1`，n0025，P-1，C16H14N2O5，R1 0.0948）|
| 结果 | 5 passed / 56.6 s；两主题均无未捕获页面错误、无 console error（WebGL/GPU 类噪音单独计数进 annotation）|

### 截图清单（`workdir/ui-evidence/r0/`）

| 文件 | 内容 |
|---|---|
| `home-{light,dark}.png` | 项目首页（"我们要对这颗晶体做些什么"）|
| `thread-structure-*.png` | 线程页 + 右栏"结构"页签，非对称单元（37 原子 · 38 键）|
| `thread-nodes-*.png` / `thread-metrics-*.png` / `thread-validation-*.png` / `thread-artifacts-*.png` | 右栏其余四个页签 |
| `thread-grow2-*.png` | 点两次"＋生长" |
| `thread-supercell-*.png` | "超胞" 2×2×2（592 原子 · 608 键）|

### 观察（这是基线，缺陷编号对应 `docs/PLAN-2026-09-04-round2.md` §1.5）

- **D4 结构不是主体**：右栏"结构"页里，头部卡 + 范围/生长/绘制/关系/证据/视图 控件区占了页签高度的约三分之二，3D 画布被压在最底部约 30% 的高度里；超胞 2×2×2 时分子挤成一团，看不出堆积。
- **D3 字号**：瓦片标签（分辨率/Rint/完整度/独立衍射/残峰/残洞 的小字）、"范围/生长/样式/元素/显示"行标、右上角"引用 ▾"都在 9–10 px 一档，1600×1000 下需要凑近才能读。
- **D2 浅色对比度**：第三级文字（侧栏"最近项目"、"本地工作台/旧版界面"、回合尾"节点 n0000_n0025 (26) · R1 0.2293→-13.4000 …"一行）明显发灰。由 `ui/src/index.css` 令牌算得（WCAG 相对亮度）：浅色 `ink-3 #9c9ca3` 对 bg 2.73:1、`accent` 4.21、`ok` 3.29、`warn` 3.39；深色 `ink-3` 3.89。这些数已固化进 `ui/src/lib/theme.test.ts` 的 `KNOWN_DEBT` - R1 换色板后必须把该列表清空，否则测试红。
- **D12/D13 左栏**：项目行没有任何状态（R1/节点/A 警报）；"旧版界面"常驻页脚；主题切换只有图标没有可读文案。
- 生长/超胞按钮本身可用（两次生长与 2×2×2 均成功渲染），但缺 Olex2 语义的菜单（Shells / Complete / 半径 pack / 装配），R1 目标。
- **D20（本轮新发现）** 回合尾统计行显示 `R1 0.2293→-13.4000`。节点库里 26 个节点的 R1 都在 0.08–0.23，负值来自 `validate_structure` 结果里的评分 `breakdown: {"r1": -13.4, "goof": 0.0, …}`（是扣分项，不是 R 值）：`ui/src/lib/resultTail.ts` 的 `bfsFind(parsed, ["r1_strong","r1_after","r1"])` 与正则回退都会抓到嵌套的 `breakdown.r1`，`threadReducer.ts:592-600` 的指标游标随后把它当成当前 R1（同理 `goof: 0.0` 也会污染 GooF）。修法放 R1 第一个提交：解析时跳过 `breakdown`/`score` 子树并对 R 值做 [0, 1] 合理性门，补 vitest 用例（用这段真实结果片段）。

### 自动守卫（本轮新增，之后每轮都跑）

| 守卫 | 位置 | 断言 |
|---|---|---|
| 构建指纹 | `server/app.py::ui_build_info` → `/api/health.ui_build`；权限菜单页脚显示 `sha[+] · MM-DD HH:mm` 并在过期时给红字提示 | `tests/test_ui_build_info.py` 7 例；`ui/e2e/health.pw.ts` 断言 `stale === false`（`CP_E2E_STRICT_HEAD=1` 时还要求 sha = HEAD）|
| 对比度 | `ui/src/lib/theme.test.ts` | 文本角色令牌对 bg/surface ≥ 4.5、对 raised ≥ 4.0；`KNOWN_DEBT` 里的令牌必须仍然失败 |
| 页面健康 | `ui/e2e/workbench.pw.ts` | 两主题：首页文案可见、右栏五个页签可点、`aside canvas` 60 s 内可见、生长 ×2 与超胞可点、无 pageerror/console.error |

### 测试基线

- pytest 全量（`.venv` 解释器，`-X utf8`，私有 basetemp）：1707 passed / 3 failed / 1 skipped（477.8 s）。3 个失败：2 个是 `tests/test_server_routes.py` 在我两次编辑 `server/app.py` 之间导入到了缺 `datetime` 导入的中间版本（`NameError`），修正后重跑 57 passed；1 个是已知负载抖动 `test_shelxt_staged.py::test_grace_exhausted_in_search`，重跑通过。**有效基线 1710 passed / 1 skipped**，再加本轮新增 `test_ui_build_info.py` 7 例。
- vitest 138 passed（含新增对比度守卫 16 例）；tsc 干净；Playwright 5 passed。
- tag：`r2-pre-r1`。

### 复现

```bash
cd ui && npm run build
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File workdir/restart_server_r13.ps1
```

```bash
cd ui && CP_EVIDENCE_ROUND=r0 npm run e2e
```

---

## R1 视觉底子（2026-09-04）

### 提交与证据轮

| 提交 | 内容 | 证据目录 |
|---|---|---|
| 4f6f91f | D20/D21：结果尾解析跳过评分/差值容器并做 R 值合理门；指标游标与画布刷新只认改模型工具（`tests/test_ui_tool_sets.py` 锁定与 `registry.MUTATING_TOOLS` 一致） | — |
| 2174ee0 | R1.1 色板、类型刻度、设置弹层、左栏状态行、旧原语令牌化 | `workdir/ui-evidence/r1a/` |
| 71bcf30 | R1.2 结构为主体：浮动工具条、Olex2 范围菜单、两行关键参数条、竖向画布的相机贴合 | `r1b/`、`r1c/` |
| 4a52fe3 | R1.3 服务端 radius / range / grow -w + 菜单接线 | `r1d/` |
| （本节） | R1.4 工作动效；最终证据轮 | `r1/` |

### 最终证据轮 r1（项目 `peeb65cea`，两主题各 12 张）

`home`、`thread-structure`、`thread-nodes/metrics/validation/artifacts`、`thread-grow2`、`thread-extent-menu`、`thread-supercell`（2×2×2，592 原子 · 608 键）、`thread-radius8`（半径 8 Å · ASU 质心，777 原子 · 798 键）、`thread-panel-draw`、`thread-panel-evidence`、`thread-header-open`。5 passed；两主题均无 pageerror / console.error。

### 观察

- **结构成为主体**：右栏"结构"页里画布占满页签高度，控件全部浮在画布上；结构卡默认折叠成两行（`n0025 main C16H14N2O5 … P-1 引用 ▸` / `R1 0.0948 wR2 0.3049 GooF 1.41 … 37 原子 · 38 键`），点击展开完整卡（式量、晶胞、R 因子、瓦片、状态行）。
- **相机贴合**：3Dmol 的 `zoomTo()` 只按竖向视场贴合，竖长画布下晶胞左右被裁（r1b 截图可见）；按宽高比回退后整胞入框（r1c 起）。
- **范围菜单**：非对称单元 / 长一层 / 长满 / 补全 / 收回 / 晶胞 / 超胞 2·3·4 / 半径 8·16 Å / 范围 −0.5…1.5 / 装配…，每项右侧标 Olex2 命令；"超胞 2×2×2"最初是空操作（reducer 只在边长变化时切模式），已改为显式切模式并加了用例。
- **色板**：浅色第三级文字、强调色、成功/警告色全部达到 AA；深色同样；`theme.test.ts` 的 KNOWN_DEBT 为空，另检查四种填充色配 `text-bg` ≥ 4.0。
- **字号**：全部 `text-[Npx]` 换成刻度类（270 处），最小 11 px；设置弹层可调 13/14/15/16 px，整套界面随之缩放。
- **元素开关**：元素色改为色点而非字色（浅色下 H 的白色字曾不可见）。
- **左栏**：项目行下多一行 `R1 0.0948 · 26 节点 · A 级 6`；主题切换与旧版入口收进齿轮弹层。
- **仍未做（留给后续轮）**：D7 叠加层随范围平铺（R2.2）、D5/D6 相互作用层（R2.3）、D17 孔心（R3）；工作动效只在回合进行中可见，本轮截图无法覆盖，需在 R5 的一格实验里看实况。

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 结果尾解析不把评分/差值当指标 | `ui/src/lib/resultTail.test.ts`（9 例，含真实 validate_structure 片段） |
| 指标游标/画布刷新只认改模型工具 | `ui/src/state/threadReducer.test.ts`；`tests/test_ui_tool_sets.py` |
| 范围菜单语义 | `ui/src/workbench/crystal/CrystalToolbar.test.ts`（5 例） |
| 切片 reducer | `ui/src/state/crystalReducer.test.ts`（+3 例） |
| 服务端切片解析解 | `tests/test_scene_extent.py`（6 例：10 Å 立方格子上 12 Å 球含 7 个分子；质心盒 12/27；grow -w 把溶剂像一并带出；缓存键） |

### 测试基线

- vitest 169 passed；tsc 干净；Playwright 5 passed。
- R1 全量 pytest（20:03–20:11，8 min 17 s）：**1724 passed / 1 skipped / 1 failed**。失败的是 `tests/test_shelxt_staged.py::TestStagedRunner::test_grace_exhausted_in_search`（计时用例：4 核限载下把 search 阶段超时判成了 phasing），单独重跑通过，属盘点时已记录的负载抖动；日志 `workdir/pytest-full-0904-r1.log`。R0 基线 1679 → 本轮 1724（+45：构建指纹 7、工具集守卫 1、切片解析解 6、其余为 R0/R1 期间追加）。
- tag：`r2-r1-done`。

---

## R2 一份成键真值 + 范围契约 + 相互作用层（2026-09-04）

### 提交与证据轮

| 提交 | 内容 | 证据 |
|---|---|---|
| 90b63dd | R2.0/R2.1：`chem/bonding.py`（smtbx 引擎 + 分类后处理器，五种 kind、每条边带判据串）、`knowledge.cn_status` 三态、现状照片 `test_bonding_status_quo`（五套判据各自固化） | tag `bonding-s1-pre` |
| e224d12 → d966969 | 六步消费者迁移，一消费者一提交：① inspect/get_geometry ② 精修用的金属接触修剪（D18）③ report/structviews ④ refine/scene（键三元组 + `m`）⑤ `analyze_connectivity`（最高风险的一次）⑥ 前端配位表删 `NON_METALS`；87e7b2d CN 只数配体；9cb9ec0 `is_metal` 周期表白名单 | 每步全量或定向 pytest；MIGRATION LOG 记录移动的数字 |
| 564e01f、b9f0c0d | R2.3：相互作用引擎（解析解 19 例）→ 场景 `interactions` 块（`?interactions=1`，缓存键 `_i1`） | `tests/test_scene_interactions.py` |
| c99f181 | R3.0/R3.1 提前：`voids.json` v3（维度 / 方向 / 内切球 / LCD；贯穿孔质心停用，D17） | `workdir/d17-check/{hex,cage}/voids.json` |
| 2290c4f | R2.2 副线合并：`range` 契约（`scene8_`）+ 客户端平铺（`ui/src/lib/tiles.ts`） | `tests/test_scene_range.py`、`tiles.test.ts` |
| 94be195 | 查看器关系图层（六个药丸、点击看几何 + 判据 + 引用）、R2.2 决策（占据胞规则、分层预算、缓存清扫）、D17 标签 | `workdir/ui-evidence/r2/` |
| 034aa39 | 副线合并：`run_shelxl(extra_cards)` 白名单通道 + HTAB → `final.cif`（D11） | 活体 SHELXL 测试 169 passed |

### 最终证据轮 r2（项目 `peeb65cea`，两主题各 14 张）

r1 的 12 张之外新增两张：`thread-voids`（证据组"孔道"药丸）与 `thread-panel-relations`（关系组同时打开 氢键 / π–π / C–H···X）。5 passed（2.0 min，含构建指纹 = HEAD 的断言）；两主题均无 pageerror / console.error。

### 观察

- **关系图层可见**（`thread-panel-relations-*`）：半径 8 Å 视图（777 原子 · 798 键）上三种相互作用以各自颜色的虚线画出，工具条"关系"徽标为 3；范围外的伙伴画到其真实位置并带对称码（边界规则），不再像旧氢键层那样在表面静默截断。两主题虚线与原子色对比正常。
- **孔道药丸在无孔结构上如实说话**（`thread-voids-*`）：`peeb65cea` 是分子晶体，掩膜无溶剂可及区域，画布右上给出"该结构无溶剂可及孔道"而不是空图层。D17 的标签（"V1 17350 Å³ · 3D · LCD 28.7 Å"，标签放在内切球心）无法在这个项目上截到，证据是 `workdir/d17-check/hex/voids.json`（3-D 网络、内切球心 (0, 0, 0.204) 在通道轴上）与 `cage/voids.json`（四个 8.6 Å³ 腔仍为 0-D、质心不变），以及 `tests/test_scene.py` 对 v3 字段的钉死。
- **成键迁移移动了哪些数**：`tests/test_bonding_status_quo.py` 的 MIGRATION LOG 逐条记录，smtbx 0.5 容差 → Σr_cov+0.45 后 scene 的键数变化、structviews 从 ×1.2 共价半径改为同一判据后多出的金属–配体键、聚合物在 cell 状态按原子折回时键数减少、CN 从"邻居数"改为"配体数"（η 环计一，金属–金属另列）。任何一处再变都会让这张照片红。
- **缺表金属不再静默通过**：`validate_structure` 对 `cn_plausible is None` 出 `metal_cn_unchecked` 提示；`metal_bonded_audit` 分开数 `n_cn_off` 与 `n_cn_unchecked`。
- **三个截断药丸各说各的**：原子已截断（`meta.truncated`）/ 图层覆盖 N / M 胞（`range.tiles_truncated`，上限 64）/ 相互作用已截断（每类 400 行）。
- **仍未做（留给后续轮）**：PLD（R3.2）、堆积指数与 Å³/非氢原子（R3.3）、客体归属（R3.4）、右栏"分析"页签（R3.5）；`htab_cards` 尚无调用方（R5 `analyze_packing`）；MPLA/RTAB 只到 `.lst` 没有 CIF 目的地；`extra_cards` 未记入 node.json；离线评分器仍用旧 `_bond_cutoff`；对称元素闭合、ASU 索引重复的芳香环（反演中心上的环）找不到（`ring_note` 已写明）。

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 成键真值：判定序、η 环、氢化物、螯合咬合、金属–金属、白名单、`as_pair_sym_table` | `tests/test_bonding.py`（46 例） |
| 五套旧判据的现状照片 + 迁移日志 | `tests/test_bonding_status_quo.py`（16 例） |
| 相互作用解析解（π–π 3.808/0.0/3.500/1.500、自转 35° α 仍 0、倾斜 25° 两侧 d⊥ 不同、O–H···O 2.75/165°、无 H 降级、P2₁/c 对称码、asu ≤ asu+光环 == cell、PART 1/2 零氢键） | `tests/test_interactions.py`（19 例） |
| 场景相互作用块：边界行 `sym`/`sym_i`、`counts.unique`、AFIX 判 `h_source` | `tests/test_scene_interactions.py`（6 例） |
| `range.tiles`：asu+生长出负平移、cell、超胞 3、截断保中心、旧 `scene7_*` 缓存被清扫 | `tests/test_scene_range.py`（5 例） |
| 孔道维度 / 方向 / 内切球解析解（LCD 13.770 Å、像原子、抽样报告） | `tests/test_pores.py`（12 例） |
| SHELXL 卡白名单、EQIV 生成、HTAB 进 CIF、MPLA/RTAB 只到 .lst | `tests/test_shelx_cards.py`、`tests/test_shelxl_tools.py` |
| 前端：配位表读 `m` 与 kind 码、相互作用文案、平铺纯函数（三斜胞偏移 = 胞矢） | `CoordinationSection.test.ts`（6）、`interactions.test.ts`（5）、`tiles.test.ts`（11） |

### 测试基线

- vitest 191 passed（169 → 191：配位表 6、相互作用文案 5、tiles 11）；tsc 干净；Playwright 5 passed。
- R2 全量 pytest（21:24–21:32，7 min 51 s）：**1885 passed / 1 skipped / 0 failed**；日志 `workdir/pytest-full-0904-r2b.log`。R1 基线 1724 → 本轮 1885（+161：成键 46 + 现状照片 16、相互作用 19 + 场景接线 6、范围 5、孔道 12、SHELXL 卡通道与活体 HTAB、其余为迁移期间追加的回归用例）。迁移中途的一次全量（`pytest-full-0904-r2a.log`，1791 passed）遇到两个负载抖动（`test_shelxt_staged` 计时、`test_probe_site` 的 state.json WinError 5），本次全量未复现。
- tag：`r2-r2-done`。

### 复现

```bash
cd ui && npm run build
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File workdir/restart_server_r13.ps1
```

```bash
cd ui && CP_EVIDENCE_ROUND=r2 CP_E2E_STRICT_HEAD=1 npm run e2e
```

---

## R3 孔道几何、堆积数字、客体位置、分析页签（2026-09-04）

### 提交与证据轮

| 提交 | 内容 | 证据 |
|---|---|---|
| 313d449 | R3.5：按节点缓存的分析产物 `refine/analysis.py`（对称唯一相互作用表 + 孔道 + 待接块）与右栏"分析"页签；相互作用行带 `intra`（同一片段 + 恒等算符 = 分子内）；判据行只列带单位的阈值；C–H···X 标签键修复（查看器卡片曾显示"?"） | `tests/test_analysis_product.py`、vitest |
| 3bfbd67 | R3.2/R3.3 副线合并：距离场、**PLD 渗流二分**、堆积数字；voids.json v4（每孔 PLD ±、整胞 packing）；分析产物 v2；计划里 PLD 期望值纠正 | `tests/test_pores.py`（37）、真实项目直跑 |
| 5b584be | R3.4 副线合并：`chem/guests.py` 宿主掩膜 + 客体归属；宿主规则在主线纠正（≥50% 最大宿主原子数的片段是宿主）；分析产物 v3；页签客体表；查看器通道方向箭头 | `tests/test_guests.py`（35）、真实项目直跑 |
| （本节） | CAPABILITIES 行、UI-EVIDENCE R3 节；最终证据轮 | `workdir/ui-evidence/r3/` |

### 最终证据轮 r3（项目 `peeb65cea`，两主题各 15 张）

r2 的 14 张之外新增 `thread-analysis`（分析页签，等到面板本身出现再截，首开要算相互作用与掩膜）。5 passed（2.0 min，构建指纹 = HEAD）；两主题均无 pageerror / console.error。

### 观察

- **分析页签**（`thread-analysis-*`）：头行"对称唯一表 · 整个晶体 · 不随显示范围变 · n0025"；相互作用 5 / 17（氢键 1 条分子内、π–π 1 条 −x+1,−y+1,−z+1 且 α 4.1°、C–H···X 15 条其中 12 条分子内、4 条满足判据）；每类下方一行判据（olex2: d_DA_max 2.9 Å、angle_DHA_min 150°），行内点亮/灰点表示是否满足，"分子内"芯片，非恒等算符以等宽字显示，悬停出"引用"。孔道段在这个分子晶体上写"该结构无溶剂可及孔道"，堆积数字 69.7 ± 0.06 %、16.4 Å³/非氢原子（直接求和是 150.6 %，不做重叠修正的"堆积指数"在致密结构上毫无意义，这就是标题数字改为并集的原因）。客体段："模型里没有客体 / 抗衡离子片段"。
- **真实项目直跑（不在截图里）**：hex n0041 3-D 网络 LCD 28.7、**PLD 28.4 ± 0.33 Å 沿 [001]**（直的六方通道，PLD ≈ LCD 合理），并集堆积 18.4 %、58 Å³/非氢原子、溶剂可及 78.5 %，去溶剂模型无客体；cage n0200 3-D 孔 LCD 5.98、**PLD 2.69 ± 0.25 Å**（窗口很窄）、四个 8.6 Å³ 腔 PLD 无定义，并集堆积 51.4 %（直接求和 96.4 %，溶剂可及 29.3 %），宿主 = 两个独立的 Zr₃ 笼（副线原规则把第二个笼当成了"通道里的客体"，主线加了 ≥50% 规则），客体 = 通道里的 C₂O₄ / C₄ / C₃ / CO 碎片（其中一个 C₂O₄ 间隙 −0.67 Å、1.10 Å 的不可能接触，表里如实列出）和一个间隙里的孤立 O；dbu n0040 阴离子（18 原子，占阳离子 37 原子的 49%）按大小规则算客体、"在通道中"——分子盐里宿主/客体只是大小规则，页签的规则行写明。
- **PLD 期望值纠错**：计划 §3.7 原写单原子简单立方 a = 10 的 PLD 沿 [100] 直线瓶颈 = 6.6 Å；渗流上确界取遍所有路径，自由球经 (½,½,0) 窗口绕行，PLD = 10.592 Å（连续扫描与 20/30/40 格二分均复现）。计划已改，测试钉的是正确值。
- **PLD 是任意方向中最宽的逃逸通道**：各向异性体系报的是宽的那条，`pld_directions` 说明是哪条；ρ* 可为负，照实报。按方向分别报 PLD 未做。
- **时间**：PLD + 堆积数字合计 ~3 s（hex），客体归属 4 s（cage）/ 1 s（hex）/ 0.2 s（dbu）；voids.json 的 70 s（hex）是 smtbx 掩膜与电子积分本来的开销，不是本轮新增；分析产物按节点缓存（`analysis.json`），二次读取 0.05 s。
- **仍未做（留给后续轮）**：PLATON 601/602 与 Olex2 headless 交叉核对夹具（R3.6：本机 `vendor/olex2/app/` 没有 `olex2c.dll`，战役目录里没有 `.chk` 文件，两条路都没有素材）；跨两个区域的客体只按质心归属；PART 无序的两个组分是两个客体记录；分子盐的宿主/客体划分；`analyze_packing` 工具（R5）读同一份产物。

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 分析产物：规范表、跨胞面一行带算符、骑乘 H 声明、截断报告、按节点缓存与版本重建（mvp-sjtu9 拷贝到 tmp） | `tests/test_analysis_product.py`（5） |
| 分子内 / 分子间：同一片段恒等算符为分子内，到自身像的接触为分子间 | `tests/test_interactions.py::TestIntraInter`（2） |
| 距离场三个解析锚点；PLD 10.592（20/30/40 格）、直线瓶颈不是瓶颈、收缩圆柱通道 3.587 vs 3.5886、0-D 无定义、方向过滤、整格粗化；堆积：单球精确、氢在球和不在原子数、27 球网格的透镜修正并集、重合球一份包络、网格上限、占有率加权 | `tests/test_pores.py`（37） |
| voids.json v4 字段（每孔 PLD / 误差 / 方向，整胞 packing） | `tests/test_scene.py` |
| 客体归属：pcu 通道、槽缝间隙（不是"离碳 1.3 Å"——那是幽灵原子）、C60 壳笼（含胞角）、P-1 胶囊分子间空腔（按实例计壁面）、去溶剂宿主、PART、宿主 ≥50% 规则 | `tests/test_guests.py`（35） |
| 前端：判据行只列阈值、C–H···X 标签、孔道引用（贯穿孔不引质心、PLD ±）、客体引用 | `interactions.test.ts`、`quote.test.ts`（vitest 197） |

### 测试基线

- vitest 197 passed；tsc 干净；Playwright 5 passed。
- R3 全量 pytest（22:41–22:49，7 min 39 s）：**1948 passed / 1 skipped / 1 failed**；日志 `workdir/pytest-full-0904-r3.log`。失败的是 `tests/test_cif_temperature.py::test_set_experiment_null_reply_is_forward_looking_not_a_false_claim`：`os.replace` 写 `context.json` 时 `PermissionError: [WinError 5]`（Windows 文件锁抖动，与 R2 中途 `test_probe_site` 的 state.json 同类），单独重跑通过。R2 基线 1885 → 本轮 1949（+64：分析产物 5、分子内 2、孔道 25、客体 35、其余为 v4 字段断言）。
- tag：`r2-r3-done`。

### 复现

```bash
cd ui && npm run build
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File workdir/restart_server_r13.ps1
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3 CP_E2E_STRICT_HEAD=1 npm run e2e
```

## R4 拓扑与形状（2026-09-04）

### 提交与证据轮

| 提交 | 内容 |
|---|---|
| 4cdc6e2 | 形状副线并入：`chem/shape.py`（CShM 钉文献常数 16.737 / 33.333 / 5.375、最大无弦环、Wadell 球形度、晶体学点对称；40 个测试） |
| 32d408c | `inspect_model` 金属环境在 tau4/tau5 旁给 CShM（η 配位球与 ≥7 顶点如实标未量）；每个工具描述末尾的参数摘要行；`situation_report` 只读堆积摘要 |
| dc062c4 | 拓扑副线并入：`chem/topology.py`（独立网与互穿的对称相关判定、节点–连接子简化网、门控 Systre、螺旋链；21 个测试 + 1 个无 jar 跳过） |
| 894b1fe | 分析产物 v4 加 `topology` 块；"分析"页签加拓扑区；查看器"关系"组加"简化网"叠加层；引用 `topologyQuote` / `fragmentQuote` |
| d5177be | `analyze_packing` 加 `topology` 块与解读句；模板 v36（7915 字符） |
| dc43e41 | e2e 把拓扑区滚进画面单独截图 |

证据轮：`r4`（项目 `peeb65cea`，nm，两主题各 17 张）和 `r4-hex`（项目 `p92391ef8`，hex MOF，两主题各 17 张），均 `CP_E2E_STRICT_HEAD=1`，服务端构建 = HEAD dc43e41。

### 最终证据轮 r4 / r4-hex（两主题各 17 张）

`home`、`thread-structure`、`thread-nodes`、`thread-metrics`、`thread-validation`、`thread-artifacts`、`thread-analysis`、**`thread-analysis-topology`**（新）、`thread-grow2`、`thread-extent-menu`、`thread-supercell`、`thread-radius8`、`thread-panel-draw`、`thread-panel-evidence`、`thread-voids`、`thread-panel-relations`、**`thread-net`**（新）。

### 观察

- **拓扑区，nm（`r4/thread-analysis-topology-*`）**：独立网"没有周期性网（分子晶体）"；简化网"结构里没有金属原子：金属簇–连接子简化不适用。这是分子晶体（所有片段 dim=0）"，RCSR 行"未算（简化网没有边：无金属节点或全为端基）"，可信度行"无金属 → 不作任何简化描述"；螺旋链"没有螺旋链"；有限片段 F1：37 原子 · 宿主 · 2 份 · C1 C10 C11 C12 …，最大无弦环 6 · 球形度 0.43 · 纵横比 0.14 / 0.72 · 最长轴 12.5 Å。头部计数"无周期网"。
- **拓扑区，hex（`r4-hex/thread-analysis-topology-*`）**：独立网 1 个 3-D 网络（510 个 P1 原子）；简化网 9 节点 / 24 边，连接数直方图 4-c ×6、8-c ×3 - N1–N3 金属簇 8-连接（O4 O5 Zr1 Zr2），N4–N9 分支连接子 4-连接（三联配体触到 ≥3 个簇按规则自成节点）；RCSR "未算（未安装 Systre）：把 gavrog 的 jar 放到 vendor/gavrog 后本项才会计算"；可信度行逐条写明 6 个分支连接子与 24 个端基连接子；螺旋链无。头部计数"1 个网"。
- **简化网叠加层，hex（`r4-hex/thread-net-*`）**：在"半径 8 Å"切片上画出节点球（金属簇橙、分支连接子青）与带晶格平移的边（灰柱），节点标签 N1…N9 只标一胞；nm 上（`r4/thread-net-*`）药丸如实写"简化网为空：没有金属节点，或连接子全为端基"，不画任何东西。
- **真实项目直跑（不在截图里）**：cage n0200 的拓扑块 7.5 s，无周期网（分子笼晶体），简化网 8 个金属节点 0 条边（72 个连接子全为端基，RCSR 状态写明原因），有限片段 F1 / F2 = 两个独立的笼 91 / 77 原子、最大无弦环 8、球形度 0.81 / 0.83，客体碎片 F3… 球形度 0.12–0.45；hex 3.3 s；nm 0.1 s。分析产物按节点缓存，产物版本 v3 → v4 的重建在页签第一次打开时发生。
- **文献常数**：正八面体对 TPR-6 = 16.737、正方形对 T-4 = 33.333（= 100/3，解析证明）、理想三角双锥对 SPY-5 = 5.375（参考角 104.9°）；R-3 上 3₁ 与 3₂ 两手皆映回同一条链 → `racemic: true` 而不选边；3₂ 的螺距是 c 不是 2c（计划 §R4 的 |t|×阶写法已在定义文本中改正）；球形度公式按 Wadell（计划公式差 4^(2/3) 倍，已改正，正八面体 0.8456）。
- **细节待改**：简化网节点的原子标签来自 P1 展开的大写（"ZR1"），页签照抄；边柱在稀疏切片上显得很长（边的另一端落在未显示的胞里），这正是"简化网随 tiles 平铺"的含义，但可以考虑只画两端节点都在显示范围内的边。
- **仍未做（写进 CAPABILITIES）**：Systre jar 未放置（RCSR 符号），.cgd 语法未经真实二进制核对；全有机网（COF/HOF）的分支点简化；有限分子的机械互锁；一维链是否真的穿套；CN 7/8 的 CShM 参考形。

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| CShM 文献常数、旋转/平移/尺度/顶点次序不变性、Berry 中点、SPY-5 参考角敏感性、最大无弦环（萘 = 6、24 元环、预算耗尽的融合梯）、球形度常数、点对称（含 48 阶 Pm-3m 位） | `tests/test_shape.py`（40） |
| `metal_environments` 的 CShM 接线：理想八面体 OC-6 且 TPR-6 16.737、正方形 vs 四面体、二茂铁不量、CN 7 未列表 | `tests/test_shape_wiring.py`（4） |
| 装饰 dia 单网 / (½,½,½) 拷贝互穿 / 独立 / P-1 操作相关；R-3 六条一维链多联锁；pcu 简化网（1 节点 6-连接 3 边、字符级 .cgd）；hcb 分支连接子；P3₁ 右 / P3₂ 左 / P2₁ null / R-3 外消旋；无 jar 时 Systre 不抛错 | `tests/test_topology.py`（21 + 1 skip） |
| 分析产物 v4 的 `topology` 块（夹具节点库 + 两个羟基的合成 .res：无网、无金属、两个有限片段、Systre 未算） | `tests/test_analysis_product.py`（+2） |
| `analyze_packing` 的 `topology` 块与解读句 | `tests/test_analyze_packing.py`（+1） |
| 前端：`topologyQuote`（互穿关系与平移、独立网、Systre 状态、螺旋）、`fragmentQuote`（标签 + 证据，不引查看器序号） | `quote.test.ts`（vitest 200） |
| e2e：拓扑区可见并单独截图；"简化网"药丸开关截图 | `ui/e2e/workbench.pw.ts` |

### 测试基线

- vitest 200 passed；tsc 干净；Playwright 5 passed × 2 轮（r4、r4-hex）。
- R4 全量 pytest：**2042 passed / 2 skipped**（23:24–23:33，9 min 14 s，无失败；R3 基线 1949 → +93：形状 40、接线 4、拓扑 21+1、参数摘要 4、堆积摘要 3、几何 7、reg8 7、分析产物 +2、analyze_packing +1 等）；日志 `workdir/pytest-full-0904-r4.log`。
- tag：`r2-r4-done`。

### 复现

```bash
cd ui && npm run build
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File workdir/restart_server_r13.ps1
```

```bash
cd ui && CP_EVIDENCE_ROUND=r4 CP_E2E_STRICT_HEAD=1 npm run e2e
```

```bash
cd ui && CP_EVIDENCE_ROUND=r4-hex CP_E2E_PROJECT='H:\CrystalPilot-campaigns\ka1-hex\p92391ef8' CP_E2E_STRICT_HEAD=1 npm run e2e
```

## R6 对话层 + 结构类别 + 视觉自审（2026-09-05）

### 提交与证据轮

- 79d4160：R6 对话层（阶段轨、回合收束、交付摘要卡、审批四面、引用锚与芯片、子代理目录）+ 结构类别（前端）+ 首轮视觉自审修补（右栏宽度随视口、窄屏侧栏抽屉、`read_skill` 卡标题）。
- 8a091b9：结构类别的服务端（项目设置 `structure_class` 校验与持久化、`get_project_brief` 实时读出）。
- 55824cd：第二轮视觉自审修补（见"观察"）+ `ui-dev` 启动项（Vite 5173 → 8010 代理，让新前端不重启服务器也能被截图）。
- 证据轮 **r6**（`workdir/ui-evidence/r6/`，nm 项目 `l44b0258e/peeb65cea`，严格 head 校验 = 55824cd）：Playwright **9 passed**（workbench 两主题 × 2 + visual-review 三种窗宽 + 深色），共 69 张。
- 视觉自审轮 **review-r6b**（`workdir/ui-evidence/review-r6b/`，对着正在跑 reg9-dbu 的活项目，经 Vite 开发服务器截 23 张：1100×700 / 1366×768 / 1920×1080 各 9 种交互状态 + 1366 深色两张）。

### 观察（我自己看图得出的，逐条对应修补）

| 看到的 | 处理 |
|---|---|
| 阶段轨在三种窗宽下都完整：`阶段 数据 7，定群 6，求解 1，建模 65，精修 23，验证 11，交付 1`，当前阶段高亮；nm 项目上停在"交付 2" | 保留 |
| 回合收束行 `已完成 · 11:49 · 节点 n0000…n0025 (26) · R1 0.2293→0.0948 · run_shelxl×7 …`、交付摘要卡（文件芯片 + "清单读自产物目录，不是从对话文字里读的"）在 nm 项目上如预期出现 | 保留 |
| "思考中… 56:26" 的置顶工作条是**通栏**的，压在下面的工具卡上，看起来像把卡切断了 | 改成居中的浮动药丸（`inline-flex`，宽度随内容） |
| 审批系统行显示 Codex 原话 `已批准 Allow the crystalpilot MCP server to run tool "checkout"?`，夹在中文卡片之间 | `describeApproval` 识别该句式，渲染为 `调用工具 checkout`；原始参数行不变 |
| 1366 px 下结构页身份条把分子式截成 `C₁₇H₂₄N₅…`，却把 `(detached from n0068)` 保留完整 | 分支标签 `shrink-[4]`，分子式后让 |
| 深色主题下 3D 画布的晶胞框（zinc-600 on #1a1a1a）几乎看不见 | 深色边线改 `#8a857b` |
| 1100 px：侧栏收成抽屉、右栏 380 px、分析页的类别条与表格仍可读；1920 px：对话列居中 768 px，右栏 570 px，画布主体 | 保留 |
| 分析页类别条：`结构类别 [未指定（按建议）] 系统建议：小分子 [采用] 依据：单一分子片段 F1（34 原子），无周期网`；选定后只展开该类别的分析区 | 保留；服务端持久化已接 |
| visual-review 规范里 `button[title="展开结构卡"]` 在结构卡默认展开时找不到，三种窗宽全部超时 | 改按 `aria-expanded` 定位，截图名改 `header-toggled` |
| `CP_E2E_PROJECT` 用正斜杠写时与状态板的反斜杠路径不相等，9 个用例全部 skip | `pickTarget` 比较前统一分隔符与大小写 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 阶段轨：最后一个成功的改模型工具定阶段、`situation_report.stage` 覆盖、回合按最多用的工具归档 | `ui/src/lib/stages.test.ts` |
| 结构类别：`sectionsFor` 按类别给区块、`suggestStructureClass` 的依据串 | `ui/src/lib/structureClass.test.ts` |
| 引用锚 `[anchor node=… atoms=…]` 的构造与解析、拓扑/片段引用 | `ui/src/lib/quote.test.ts` |
| 服务端：`structure_class` 只接受五个值或 null，`get_project_brief` 实时读文件、坏 JSON 视为未声明 | `tests/test_structure_class_setting.py`（4） |

### 测试基线

- vitest **219 passed**；tsc 干净；Playwright 9 passed（r6）+ 4 passed（review-r6b）。
- 全量 pytest **2049 passed / 2 skipped**（2026-09-05 00:35–00:45，10 min 16 s，`workdir/pytest-full-0905a.log`；R4 基线 2042 → +7：预热 3、结构类别 4）。
- tag：`r2-r6-done`。

### 复现

```bash
cd ui && npm run build
```

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File workdir/restart_server_r13.ps1
```

```bash
cd ui && CP_EVIDENCE_ROUND=r6 CP_E2E_STRICT_HEAD=1 CP_E2E_PROJECT=H:/CrystalPilot-campaigns/l44b0258e/peeb65cea npm run e2e
```

```bash
cd ui && CP_BASE_URL=http://127.0.0.1:5173 CP_EVIDENCE_ROUND=review-r6b npx playwright test e2e/visual-review.pw.ts
```

## R5 工具面 + 一格端到端（2026-09-05）

### 提交与证据轮

- R5 代码：`analyze_packing`、`get_geometry` 三个 scope、参数摘要行、`situation_report` 阶段/堆积摘要、reg8 四项、规格缓存内容指纹、模板 v36（见 CAPABILITIES §3、§8）。
- a311653：P0 - numpy + scipy 在 anyio 循环之前导入、cctbx 系主线程预热、冷进程 stdio `analyze_packing` 回归（reg9-dbu 的 35 min 卡死）。
- 8446611：两条已知答案校验副线并入（相互作用 / 拓扑-孔道；CAPABILITIES §7b）。
- 端到端：reg9-dbu（acceptable，卡死暴露 P0）→ reg10-dbu（**publication**，R1 0.0463 / Δ 0.0016，`analyze_packing` 1.4 s 返回，`HTAB N2 O1` 进 `final.cif` 带 esd）。草稿 `docs/reg1-2026-09-04/REG9-DBU-draft.md`、`REG10-DBU-draft.md`。
- 证据轮 **r5**（`workdir/ui-evidence/r5/`，reg10 项目 `l059c1b05/p0d672e05`，严格 head 校验 = 23389cd）：Playwright **9 passed**（workbench 两主题 + visual-review 三种窗宽 + 深色）。

### 观察

| 看到的 | 处理 |
|---|---|
| 阶段轨停在"交付 6"，回合收束行 `已完成 · 28:31 · 节点 n0000…n0057 (58) · R1 0.1544→0.0463 · run_shelxl×26 branch×13 inspect_model×11 …`，交付摘要卡带 `豁免 11` 芯片与 10 个文件芯片 | 保留（R6 的组件在 R5 的真实交付上如预期） |
| 分析页氢键行 `N2–H1···O1 D···A 2.78 Å · H···A 1.89 Å · ∠ 175.7°` 与 `final.cif` 的 `_geom_hbond_` 行 `2.778(2) / 1.89(2) / 175.7(19)` 一致（同一节点 n0057，H 已自由精修） | 保留：页签、`analyze_packing`、CIF 三处同源 |
| 身份条分子式 `C₁₈H₂₄N₄O₆`，而 CIF 的 `_chemical_formula_sum` 是 C16H20N4O6：无序两位（C14/C15 各两套 + H）按原子个数计了两遍 | 待修：分子式应按占有率求和（见下一轮） |
| 结构类别条：`未指定（按建议） 系统建议：小分子 采用 依据：单一分子片段 F1（34 原子），无周期网` | 保留 |

### 测试基线

- 合并后针对性测试（预热、孔道、拓扑、相互作用、分析产物、analyze_packing、场景、几何、两个已知答案文件）**248 passed / 24 skipped**（6 min 53 s，`workdir/pytest-merge1.log`；跳过全部是"该结构没有落在窗口内的可比行 / 没有记录的边界例"，PLATON 交叉确实跑了）。
- 全量 pytest 见 R6 节（2049 / 2，同一天更早）；本节之后的全量在 R7 收尾时再跑。
- vitest 219 + 1；tsc 干净；Playwright 9 passed（r5）。
- tag：`r2-r5-done`。

### 复现

```bash
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m crystalpilot.benchmark.agent_campaign H:/CrystalPilotData/campaigns/reg10-dbu.json
```

```bash
cd ui && CP_EVIDENCE_ROUND=r5 CP_E2E_STRICT_HEAD=1 CP_E2E_PROJECT=H:/CrystalPilot-campaigns/l059c1b05/p0d672e05 npm run e2e
```

## R7 子代理（2026-09-05）

### 提交与证据轮

- 23a34f0：R7 地基（Sonnet 副线），Codex 0.147.0 自定义角色调研 `docs/R7-SUBAGENT-GROUNDWORK.md`、四个只读审计角色、守卫测试。
- 探针（`workdir/r7-probe/run.log`、`run2.log`，一次性项目）：项目级角色经 app-server 可拉起（`fork_turns="none"`）；子代理另起 MCP 进程，角色自带只读覆盖时 `readonly: true`，`edit_atoms` 被服务端拒绝。见 `docs/reg1-2026-09-04/SUBAGENT-TRIAL.md` §1。
- 7fab11a：落地，模板 v37 + delegate 变体、按项目写/删角色文件、设置 `subagents`/`delegation`、UI 开关与状态行、系统行"已进入/退出委派档位"。
- 证据轮 **r7**（`workdir/ui-evidence/r7/`，nm 项目，严格 head 校验 = 7fab11a）：Playwright **9 passed**。

### 观察

| 看到的 | 处理 |
|---|---|
| 权限菜单"项目设置"里新增一行：`只读审计子代理（最高档提示）` 开关（默认开）+ 说明 + 状态行 `当前档位已开启：角色 chemistry / density / space_group / validation`（nm 项目默认档位就是 xhigh） | 保留；低档位时状态行写"当前未开启（需最高档 xhigh）"，关掉写"已关：任何档位都不提示、不生成角色" |
| 状态行的四个角色名是英文标识符（与 `spawn_agent(agent_type=…)` 一致），说明文字是中文 | 保留：标识符必须与 agent 看到的一致 |
| 其余页面与 r6 一致（阶段轨、交付摘要、分析页类别条） | 保留 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| delegate 变体：独立标记、含 `fork_turns="none"` 与四个角色名、正文 < 9000、`ensure_agents_md` 在两种变体间切换、记录块带 `delegation` | `tests/test_agents_md.py::test_delegate_variant_is_a_distinct_marked_rendering` |
| 角色文件：字段、只读沙箱、不提任何写类工具、长度预算；按项目渲染带 `--project` 与 `CRYSTALPILOT_MCP_READONLY=1`；开/关时写入/删除、外来文件不动 | `tests/test_codex_agent_roles.py`（36） |
| 设置：`subagents` 只接受 top_tier/off，`delegation.active` = 策略 × 有效档位；改档位/策略即重写模板与角色并推送 `delegation` 事件 | `tests/test_structure_class_setting.py::test_delegation_tier_in_settings_and_update` |

### 测试基线

- vitest 222；tsc 干净；Playwright 9 passed（r7）。
- 全量 pytest **2208 passed / 25 skipped / 1 failed**（2026-09-05 09:12–09:26，13 min 26 s，`workdir/pytest-full-0905c.log`）：失败的是 `tests/test_shelxt_staged.py::TestStagedRunner::test_grace_exhausted_in_search`（staged SHELXT 的宽限计时，全量负载下超时；单独重跑该文件 27 passed），已知的负载抖动项，不是回归。R6 基线 2049 → +160：已知答案 37 + 相互作用/拓扑修复回归、角色 36、委派 4、runner 重试 2、通知归一化 2 等。
- 一格对照：reg11-cage（委派 2 次，死于流中断 + 主机崩溃）→ reg12-cage（委派 3 次，below_bar，机制可用、未证明有益；`docs/reg1-2026-09-04/SUBAGENT-TRIAL.md`）。
- tag：`r2-r7-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r7 CP_E2E_STRICT_HEAD=1 CP_E2E_PROJECT=H:/CrystalPilot-campaigns/l44b0258e/peeb65cea npm run e2e
```

```bash
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 workdir/r7_probe.py
```

## 第三轮 R0–R1：基线、事件身份与长会话稳定性（2026-09-05）

### 提交与证据轮

- beece50：R0 - `scripts/restart_server.ps1`（按命令行识别 uvicorn、PID 文件、固定日志）、`scripts/run_live.py`、六档推理档位（探针 `docs/reg1-2026-09-04/EFFORT-PROBE.md`）、计划 `docs/PLAN-2026-09-05-round3.md`；tag `r3-pre`。
- c443fff：R1 前端，四区 ErrorBoundary + `lib/diagnostics.ts`、`ReasoningBlock` 空载荷防御、折叠顺序/插话/秒→毫秒、指标页标注。
- 1315218：R1 服务端+客户端，`eid` 事件身份、transcript 分页、`channel_hello{generation}`、命令完整输出落盘与端点、`POST /api/ui/diagnostics`；前端 eid 去重、分页重建、"更早的输入"常驻、命令卡"查看完整输出"。
- 0c8794b：并发冷启动修复（第一格实机暴露：两个 MCP 进程同秒导入起始模型撞在共用临时文件上）。
- 证据轮 **r3-pre**（`workdir/ui-evidence/r3-pre/`）：Playwright 16 passed / 4 skipped（基线，含 R1 前端提交）。
- 证据轮 **r3-r1**（`workdir/ui-evidence/r3-r1/`）：`reconnect.pw.ts` 3 passed，跑在 10 224 行的实机演示线程上（`H:\CrystalPilot-campaigns\live-demo-20260905-1503\mof`）；一格真实小分子 org_hsl 的运行态/完成态截图。

### 观察

| 看到的 | 处理 |
|---|---|
| `reconnect-all-pages.png`：逐页"加载更早的记录"后，线程从暖机的"就绪"起完整可见，5 条人类输入（含 1 条插话）各出现一次，刷新后同样 | 保留；这是 F-1/F-3/F-4 的直接证据 |
| `live-org-hsl-2-running-01.png`：阶段轨停在"验证"，状态药丸"思考中… 05:59"，右栏 n0007 R1 0.0263，节点树 12 节点，上下文 41% | 运行态真实证据；R2-A 会把药丸与阶段轨合并为状态行 |
| `live-org-hsl-2-done-light/dark.png`：交付摘要卡 `final · 豁免 11`，文件芯片里混着 `command_output\call_….txt` 与 `transcript.jsonl` | R2-B 交付卡按版本分组、只列四类主文件时过滤日志类文件 |
| 第一格（`live-org-hsl-running-01.png`）整场只有 `crystalpilot_error` 卡、"project failed to open" | 根因与修法见 `docs/reg1-2026-09-04/R3-R1-draft.md`；项目目录保留为取证现场 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 事件身份：行号 eid、分页 `before/limit`、损坏行不移位、命令输出端点路径守卫、SSE hello、诊断端点 | `tests/test_transcript_paging.py`（17） |
| 取证夹具回放：83 行 + 2 条 SSE 重放（无 eid 复现幽灵卡 / 有 eid 零新增）、5 条人类输入的 SSE/transcript 双形态、eid 窗口、分页重建、命令输出规则 | `ui/src/state/threadReducer.eid.test.ts`（夹具 `ui/src/state/__fixtures__/`） |
| 折叠顺序/插话/秒换算、SHEL 工作截断、诊断上报与限流 | `messageGrouping.test.ts`、`shel.test.ts`、`diagnostics.test.ts` |
| 并发冷启动：6 写者、三进程同刻打开新项目、锁的三种异常持有者、句柄重试 | `tests/test_concurrent_open.py`（7） |
| 真实长线程刷新/分页/hello 代际/诊断端点 | `ui/e2e/reconnect.pw.ts`（3） |

### 测试基线

- vitest 283；tsc 干净；Playwright 16 passed / 4 skipped（r3-pre）+ 3 passed（r3-r1 reconnect）。
- 全量 pytest：见 `docs/reg1-2026-09-04/R3-R1-draft.md` §四（`workdir/pytest-full-r3r1.log`）。
- 一格实机：org_hsl 16 min 38 s / 53 次工具，评分 publication（`workdir/campaigns/r3-r1/GRADE-org-hsl-2.json/`）。
- tag：`r3-r1-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r1 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\live-demo-20260905-1503\mof' npx playwright test e2e/reconnect.pw.ts
```

```bash
.venv/Scripts/python.exe -X utf8 scripts/run_live.py --source H:\CrystalPilot-campaigns\ka1-org\p813c1570 --context H:\CrystalPilot-campaigns\ka1-org\p813c1570\context.json --name r1-org-hsl-3 --brief workdir/live-demos/briefs/r1-org-hsl.md --structure-class small_molecule --hours 1
```


## 第三轮 R2：主会话栏（R2-A）与侧栏 / 查看器（R2-B）（2026-09-05）

复盘：`docs/reg1-2026-09-04/R3-R2-draft.md`。

### 提交与证据轮

- 6c2ff94：MCP 启动探针（`resources/templates/list`、`prompts/list` 返回空表）+ 新建/续接会话首回合等待工具注册（`mcp_startup` 系统行落 transcript）。
- 26065ac：R2-A - `StatusRail`（✓/●/○ 阶段 + 一条动作行，5 分钟静音）、`ToolCard` 单行化（失败行 3 px 左条 + 原因行内）、简洁模式隐藏自动审批、`DeliveryCard`（状态芯片 / 节点 / R1 wR2 GooF / 五个主文件 / 全部 N 个文件 → 产物页签）、"回到最新"、动效目录。
- R2-B 提交（`git log r3-r1-done..r3-r2-done`）：相机只框原子 + "居中"、范围菜单分 范围/动作、ink-2/ink-3 加深（≥ 5:1 守卫）、左栏显示名/改名/"更多"、身份栏两行、节点树折叠 + 车道打包 + 沿用/已交付/最优标记、聚焦模式、产物页按交付分组；服务端 `deliveries` 与 `display_name`。
- 证据轮 **r3-r2a**（`workdir/ui-evidence/r3-r2a/`）：Playwright 13 passed（org_hsl 完成态 浅/深/1100、运行态、回合后、续接等待 MCP）。
- 证据轮 **r3-r2b / r3-r2b-mof / r3-r2b-cage**：`e2e/r2b-layout.pw.ts` 6 用例（900 / 1100 / 1440 × 浅深）在小分子 org_hsl-2（14 节点）、Zr-MOF 演示（225 节点，45 + 6 条分支）、Zr6 笼（189 节点，72 条诊断分支）上各 6 passed；全套回归（既有用例，org_hsl-2）：25 passed / 4 skipped（跳过的 4 个为缺结构文档夹具与进度传输夹具的既有用例，与 r3-pre 基线相同；含 300 px 侧栏 × 13/16 px、visual-review 三宽 + 深色、workbench 生长/超胞、reconnect 三例）。

### 观察

| 看到的 | 处理 |
|---|---|
| `r3-r2a/org-hsl-done-light.png`：状态行"✓ 数据 … ● 交付 ｜ 空闲 · 上次回合 16:38 · 节点 n0013"，工具行单行、失败原因行内、交付卡"定稿 · 豁免 11 · 节点 n0013 · R1/wR2/GooF · 5 个主文件 · 全部 11 个文件 → 产物页签" | 保留 |
| `r3-r2b-mof/1440-light-thread.png`：Zr-MOF n0224 的 Zr2 簇 + 配体撑满画布（相机修复前是 39 Å 胞中央一小团） | 保留；晶胞框只在画布角落露出 |
| `r3-r2b-mof/1440-light-nodes.png`：45 条非诊断分支折成分支头、3–4 条车道，未精修节点写"沿用 n0219" | 保留 |
| `r3-r2b-cage/1440-light-nodes.png`："诊断分支 72 条 · 153 节点"一行收起 | 保留 |
| `r3-r2b/1440-light-thread.png`：左栏"小分子 org_hsl · R1 实机验证"，最近项目无 ui-import，"更多 21" | 保留 |
| 1440 px 默认右栏 432 px 下，身份栏行 2 的长化学式仍截断（title 有全式） | 计数显示阈值提到 480 px；再宽的化学式就靠 title |
| 工具失败行原因仍是英文原话 | R3 WP1 结构化错误后中文化 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 状态行模型（审批 > 工作 > 上次回合三态、5 分钟静音、阶段三态）、交付事实（真实 org_hsl 载荷） | `ui/src/lib/statusRail.test.ts`、`delivery.test.ts` |
| 范围菜单顺序与分组、收回的位置 | `ui/src/workbench/crystal/CrystalToolbar.test.ts` |
| ink-2 / ink-3 在 bg/surface/raised 上 ≥ 5:1（两主题） | `ui/src/lib/theme.test.ts` |
| 节点树：分支头/折叠/诊断家族行、R1 来源（沿用）、树内最佳不含诊断分支、分叉落点、车道打包与复用 | `ui/src/lib/nodeTree.test.ts`（7） |
| 产物分组：顶层优先、主文件次序、日志分离、任务目录还原、MANIFEST 匹配 | `ui/src/lib/artifactGroups.test.ts` |
| 最近项目折叠：路径键、ui-import 判定、隐藏/溢出进"更多" | `ui/src/workbench/sidebar/hiddenProjects.test.ts` |
| 显示名（设置 > context 标题 > 无）、注册表不存名、改名归一化、交付标记扫描与节点路由 | `tests/test_project_display_name.py`（7） |
| MCP 探针与首回合等待 | `tests/test_mcp_probes.py`、`tests/test_mcp_ready_wait.py`（5） |
| 三个真实项目 × 三宽 × 两主题：身份栏不溢出且截断带 title、菜单分组、诊断行收起、图宽 < 半面板、折叠/展开、当前查看恰一行、产物无反斜杠、聚焦 ≥ 60%、Esc 退出、左栏名字、零页面错误 | `ui/e2e/r2b-layout.pw.ts`（6） |

### 测试基线

- vitest 312；tsc 干净；Playwright r3-r2a 13 passed；r2b-layout 6 × 3 项目 passed；全套：25 passed / 4 skipped（跳过的 4 个为缺结构文档夹具与进度传输夹具的既有用例，与 r3-pre 基线相同；含 300 px 侧栏 × 13/16 px、visual-review 三宽 + 深色、workbench 生长/超胞、reconnect 三例）。
- 全量 pytest：2368 passed / 25 skipped / 0 failed（2026-09-05 23:07，10 min 54 s，仓库外 basetemp，`workdir/pytest-full-r3r2.log`；R1 时 2355）。
- tag：`r3-r2-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r2b-mof CP_E2E_PROJECT='H:\CrystalPilot-campaigns\live-demo-20260905-1503\mof' npx playwright test e2e/r2b-layout.pw.ts
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r2b CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r1-org-hsl-2' npx playwright test
```

## 第三轮 R3：工具面 P0：状态与诚实（2026-09-05/06）

复盘：`docs/reg1-2026-09-04/R3-R3-draft.md`。前端本轮只改了"读新字段"的三处：工具行首的信封芯片（无变化 / 未定论 / 证据相反 / 超时 · 部分结果 / 已取消）、`preflight_restraints` 新卡与 `set_restraints` 的跨 PART 告警、`audit_guest_evidence` 卡的工作占有率与"受限制/共享变量约束"芯片。

### 提交与证据轮

- `76e3728` WP1 / WP6 / T-k：`summary.tool_status` 分层结果信封（`tools/base.py::invoke` + `project.invoke_tool` 前后节点），`resultTail.ts` 把它列为非指标容器，`toolCards.envelopeChips` 行首芯片；诊断删除记 `diagnostic_touches` 不改处置；`situation_report` 掩膜块读 `solvent_mask_info`。
- `4be3b40` WP8 / T-j：`tests/test_schema_bounds.py` 守卫 + 首批 7 处 minimum/maximum（参数摘要行 `number[0.5..6]`）；知识卡与掩膜诊断改条件句；配位客体措辞。
- `4db0928` WP3：`refine/parts.py`（删除清 PART 状态、组空丢弃 + FVAR 重编、分裂记录 stale）、`edit_atoms(set_part/clear_part)` + `model_disorder(undo=<label>)`、`restraints.preflight()`、第 71 个工具 `preflight_restraints`（AGENTS 一行 + UI 卡 + READ_ONLY）。
- `bd6a3ba` WP4：客体证据逐原子记账、分母带标签、循环数与终止原因、`conditioned_by_prior`、`scientific_outcome`；卡片加工作占有率芯片。
- `8fd59a2` WP2：`flags.effective_cards` → `node.json.effective_state`（schema 2）→ `model.res` / final.res；checkout 还原、后续作业自动带入、`replace_cards`、删原子修剪、导入带卡；`write_outputs.restartable`。
- 证据轮 **r3-r3**（`workdir/ui-evidence/r3-r3/`）：`e2e/r2b-layout.pw.ts` 6 用例（900 / 1100 / 1440 × 浅深）在实机 DBU 盐项目（29 节点 / 5 分支，定稿 R1 0.0445）上 6 passed。

### 观察

| 看到的 | 处理 |
|---|---|
| `r3-r3/1440-light-thread.png`：状态行"✓ 数据 … ● 交付 ｜ 空闲 · 上次回合 23:42 · 节点 n0028"；交付卡"定稿 · 豁免 9 · 节点 n0028 · R1 0.0445 wR2 0.1121 GooF 1.01 · 5 个主文件 · 全部 9 个文件"；第一次 `finalize_delivery` 的失败行是单行 + 3 px 左条 + 原因行内 | 保留 |
| 同图：一条 shell 命令失败行（agent 用 apply_patch 向结果目录加文件，退出码 124）被折进"过程 · 6 条命令"之外单独显示 | 保留（错误永不折叠的规则在起作用）；模板下一轮说清写交付说明走工具 |
| `r3-r3/1440-light-nodes.png`：5 条分支折叠成分支头；n0028 标"已交付"，n0026 标"R1 最优 0.0431"（被放弃的试验分支）；未精修节点写"沿用 n0020" | 保留，树如实显示最优 R1 不在交付节点上，不替 agent 挑赢家 |
| 结构画布：DBU 阳离子的两套环构象（PART 1/2 都画）与硝基苯甲酸根 | 保留 |
| 工具行的信封芯片在这一格里没有出现"无变化 / 未定论"（没有零新增的 fit_fragment、没有掩膜） | 单元测试覆盖（`toolCards.envelope.test.ts`）；下一格 MOF 复跑（R4）会看到 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 信封：refine → changed、list_nodes → unchanged、抛错 → failed 且旧 ok/error 不变、预算超出 → timeout、取消 → cancelled、fit_fragment 零新增 → no_change + inconclusive、掩膜块有数字 | `tests/test_result_envelope.py`（13） |
| 运行时边界必须在 schema 声明；参数摘要行显示 `[lo..hi]` | `tests/test_schema_bounds.py`（参数化，每处一例） |
| PART 生命周期：删除清附属状态、同名重加不继承、组空丢弃 + FVAR 重编、stale 拒撤销、set_part/clear_part 与撤销、原子性、预检冲突、set_restraints 报告、工具注册 | `tests/test_part_lifecycle.py`（18） |
| 客体记账：分母标签与工作假设、满占模型读 against、特殊位置多重度、0 循环 inconclusive、混合组逐原子 | `tests/test_guest_evidence.py`（10） |
| 有效模型状态：采纳即状态、随后续作业与提交、check 不持久化、replace、checkout 还原、删原子修剪、失效卡拒绝、卡片读取 / 一致性 / 修剪 / 重命名、交付一致性点名、导入带卡 | `tests/test_effective_state.py`（11） |
| 诊断删除绕过账本处置、主线仍受保护 | `tests/test_probe_site.py::TestLedgerIsolation` |
| 信封芯片、tool_status 不被读成指标 | `ui/src/lib/toolCards.envelope.test.ts` |

### 测试基线

- vitest 315（35 个文件）；tsc 干净；`npm run build` 2026-09-05 16:09Z（服务器随后受管重启，health 200）。
- 全量 pytest：**2425 passed / 25 skipped / 0 failed**（2026-09-06 00:27，12 min 17 s，仓库外 basetemp，`workdir/pytest-full-r3.log`；R2 时 2368）。
- Playwright r3-r3：6 passed（实机 DBU 项目）。
- tag：`r3-r3-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r3 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r3-dbu' npx playwright test e2e/r2b-layout.pw.ts
```

## 第三轮 R4：整客体工具与研究目标（2026-09-06）

复盘：`docs/reg1-2026-09-04/R3-R4-draft.md`。前端本轮新增四张工具卡（`search_fragment_pose` 候选数 / 首选证据计数 / 对称折叠；`accept_fragment_pose` FVAR / PART / EADP / 节点芯片；`set_investigation` 两级达成 / 已否决 / 未试方向；无新页面），`threadReducer.ts` 的改模集合补 `accept_fragment_pose`。

### 提交与证据轮

- `b2cdebb` WP5：`refine/tools_pose.py`（搜索 + 接受）、注册 / 预算 / READ_ONLY / MUTATING、AGENTS 一行、两张卡、阶段映射。
- `8bfd65a` WP7-a：`refine/trial_ledger.py` + `project.invoke_tool` 钩子 + `situation_report.recent_trials`；UI 改模集合补漏。
- `5f7f421` WP7-b：`refine/investigation.py` + `set_investigation` + `finalize_delivery` 诊断门 + AGENTS v39 + 卡。
- `0b0c761` R4-c：客体检验 3 位移对照、姿态候选锚点优先。
- 证据轮 **r3-r4**（`workdir/ui-evidence/r3-r4/`，36 张）：`e2e/r2b-layout.pw.ts` 6 用例在实机 r4-mof 项目（117 节点 / 51 分支，诊断交付 n0109）上 6 passed。

### 观察

| 看到的 | 处理 |
|---|---|
| `r3-r4/1440-light-thread.png`：状态行"✓ 数据 … ● 交付 ｜ 空闲 · 上次回合 42:36 · 节点 n0116"；回合收束行"已完成 · 42:36 · 节点 n0000…n0116 (40) · R1 0.1822→0.0860 · run_shelxl×13 branch×9 run_shelxt×7 ghost_test×7 … · shell×18" | 保留 |
| 同图：`solvent_mask` 失败行（"计算溶剂掩膜 失败 · 0.6 s"）单行红字；一条 shell Python 脚本失败（KeyError，退出码 1）作为命令卡单独显示，未折进"过程 · 57 次工具 · 3 条命令 · 17:15" | 保留（错误永不折叠） |
| 交付摘要卡"诊断性 · 节点 n0109 · R1 0.0860 wR2 0.2640 GooF 0.91 · final.cif / final.fcf / final.res / SUMMARY.md / VALIDATION.md · 全部 15 个文件 → 产物页签" | 保留 |
| 右栏身份栏：n0109 · delivery-diagnostic · P6/mmm · C14H6O6Zr2（ASU）· R1 0.0860 ▼0.0076 · wR2 0.2640 ▼0.1255 · GooF 0.91 ▲0.08；左栏项目行"r4-mof · R1 0.0860 · 117 节点 · A 级 8" | 保留 |
| 本格没有触发 `prior_trial`（同节点同输入重跑 0 次），所以账本芯片没有实机截图 | 单元测试覆盖（`tests/test_trial_ledger.py`）；下一格再看 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 姿态搜索：藏 0.3 占有率苯环 ≤0.4 Å、错锚点点名、反演中心折叠 3 原子、预算耗尽返回部分结果、接受恰一个节点（FVAR2 / PART / EADP）、undo 拒绝片段 FVAR、删除清理 | `tests/test_fragment_pose.py`（12） |
| 试验账本：键归一化（标签序 / 大小写 / 浮点噪声 / 预算键）、坐标保序、旁支忽略、损坏文件读空、同节点 prior_trial、祖先只告知、失败不记、situation_report 列最近试验 | `tests/test_trial_ledger.py`（9） |
| 研究目标：记录往返与部分更新、met 需证据、SESSIONLESS 且不建节点、situation_report 携带、诊断封存写未达层级 / 未试方向、unmet_goals 兜底、final 不受门 | `tests/test_investigation.py`（7）+ `tests/test_finalize_delivery.py` |
| 客体检验 3 位移对照：合成客体回到 ≥50%、合成幽灵回不来 → inconclusive | `tests/test_guest_evidence.py`（11） |
| 改模集合与注册表一致（抓到 accept_fragment_pose 漏项） | `tests/test_ui_tool_sets.py` |

### 测试基线

- vitest 315（35 个文件）；tsc 干净；`npm run build` 2026-09-05 17:26Z（服务器随后受管重启，health 200，`llm_configured: true`）。
- 全量 pytest：2457 passed / 24 skipped / 3 failed（10 min 28 s，`workdir/pytest-full-r4.log`；三个失败是模板措辞 / 总长与工具分类守卫，修复后相关套件 73 passed；R3 时 2425 passed）。
- Playwright r3-r4：6 passed（实机 r4-mof 项目）。
- tag：`r3-r4-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r4 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r4-mof' npx playwright test e2e/r2b-layout.pw.ts
```

## 第三轮 R5：师兄功能正确性与范围自适应（2026-09-06）

复盘：`docs/reg1-2026-09-04/R3-R5-draft.md`。前端本轮：范围菜单"长满"变成真正的 Olex2 `grow`（服务端 `grow_all=1`，药丸"周期截断 / 原子预算截断"），分析页孔行加"沿 a/b/c x/y/z Å"，孔道块加"重算掩膜电子 · 精修掩膜快照"两数并列（差 >20 % 加 ⚠ 与提示），拓扑区显示互穿判定（互穿 / 不互穿 / 未判定）；新证据用例 `e2e/r5-analysis.pw.ts`。

### 提交与证据轮

- `5ce7154` R5-A 对称闭合环；`f27453d` R5-B 长满；`373de4f` R5-E 环穿越互穿；`e2de771` + `89b5ea1` R5-C/D 沿轴 PLD 与电子数口径；`a5e71e5` R5-F 已知答案。
- 证据轮 **r3-r5**（`workdir/ui-evidence/r3-r5/`，48 张）：`e2e/r2b-layout.pw.ts` 6 用例在 Zr6 笼项目（pe8f898bd，189 节点）上 6 passed；`e2e/r5-analysis.pw.ts` 在 r4-mof（117 节点，n0109）与笼项目上各 2 passed（浅 / 深）。

### 观察

| 看到的 | 处理 |
|---|---|
| `r3-r5/r4mof-analysis-pores-light.png`：孔道块 "V1 16996 Å³ · 3-D 网络 · LCD 11.5 Å · PLD 8.2 ± 0.33 Å · 沿 a/b/c 6.2/6.2/8.2 Å · 1193 e"，下一行 "重算掩膜电子 1193.2 e/胞 · 精修掩膜快照 591.6 e/胞 ⚠"；查看器身份栏 "非对称单元（长满）" + 药丸 "周期截断" | 保留；2.02 倍的来源记入复盘 §5 |
| `r3-r5/r4mof-grow-all-*.png`：Zr-MOF 长满 647 原子、93 个周期帽，`complete=false` | 保留（周期网只长一个周期是 Olex2 语义） |
| `r3-r5/cage-grow-all-*.png` / `cage-analysis-*.png`：Zr6 笼项目的长满与分析页（有限片段） | 保留 |
| 首次运行 `r5-analysis.pw.ts` 失败：分析页各段就绪后 `analysis-stage-<name>` 通知元素被段落本体替换，等待器找不到 | 给孔道段加 `data-testid="analysis-pores"`（与 `analysis-topology` 同式），用例改等段落或 error 通知 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 对称闭合环：反演中心苯环建 6 原子并与晶格像堆积、三次轴苯环 2 原子建 6、整环写全对照、晶格回路不计 | `tests/test_interactions.py`（26） |
| 长满：跨胞边界分子补全、链两端帽、反演中心环补全（一层生长只到 5）、bcc 网停在晶格重复、预算截断如实、缓存键 `_ga1`、不开开关无变化 | `tests/test_scene_grow_all.py`（10） |
| 环穿越：MOF-5 平移拷贝 / 反演双重互穿 → true，平行层 → false，螺旋链对 not_testable，预算耗尽 null，pcu / dia 窗口计数 | `tests/test_topology.py`、`tests/test_known_answers_topology.py` |
| 沿轴 PLD：立方胞三轴同值、沿 c 圆柱 a/b 为 null、空腔无条目、超预算给说明；几何孔道路径带沿轴 PLD | `tests/test_pld_along.py`（4）、`tests/test_upgrade_structure_document.py` |
| 电子数口径：一致 / 不一致 / 无快照 / 仅快照四种情形的纯函数与阅读句，产物携带 | `tests/test_analyze_packing.py`（+2） |
| 已知答案：COD 2232050 阴离子–π + π–π + 5 条氢键；COD 4115425 6₁ 螺旋；PLATON π–π 最少比对行数（Zn2_dhtp 12） | `tests/test_known_answers_interactions.py`、`tests/test_known_answers_topology.py` |

### 测试基线

- vitest 315（35 个文件）；tsc 干净；`npm run build` 2026-09-06（受管重启，health 200）。
- 全量 pytest：2486 passed / 26 skipped / 0 failed（13 min 11 s，2026-09-06）（`workdir/pytest-full-r5.log`，仓库外 basetemp；R4 时 2457 passed）。
- Playwright r3-r5：6 + 2 + 2 passed。
- tag：`r3-r5-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r5 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\reg12-cage\pe8f898bd' npx playwright test e2e/r2b-layout.pw.ts
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r5 CP_E2E_TAG=r4mof CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r4-mof' npx playwright test e2e/r5-analysis.pw.ts
```

## 第三轮 R6：人机交互（2026-09-06）

复盘：`docs/reg1-2026-09-04/R3-R6-draft.md`。前端本轮：提问卡（对话静态卡 + 输入框上方停靠卡，一键 `[prior]` 回复）、插话回执（发送中 / 已记录 / 已送达模型 / 未送达模型 + 重试）、草稿引用芯片、对话锚芯片跳转、设置菜单的知识模式与结构类别；新证据用例 `e2e/r6-interaction.pw.ts`。

### 提交与证据轮

- `b42b9ca` R6 全部代码（模板 v40、`steer_receipt`、UI）。
- 证据轮 **r3-r6**（`workdir/ui-evidence/r3-r6/`，8 张）：`e2e/r6-interaction.pw.ts` 在 Zr6 笼真实项目（pe8f898bd）上 2 passed（浅 / 深）。**UI 证据而非科学证据**：真实 transcript 末尾由路由拦截追加一段明确合成的尾巴（一张卡、两条带回执的插话），`/api/threads/send` 与 `/api/threads/steer` 被拦截并记录请求体，没有消息到达模型。

### 观察

| 看到的 | 处理 |
|---|---|
| `r6-light-card-receipts.png`：对话里静态卡（已确定 / 分歧 / 问题 / 不知道时 + 三个选项药丸），输入框上方停靠卡（同样四行 + 有 / 没有 / 不知道 / 自己回答 + 提示句）；两条插话分别标"已送达模型"和"未送达模型 重试" | 保留 |
| 点"有"后请求体正文 = `[prior] 问题：合成时是否加入了对溴苯乙酸？\n回答：有`，停靠卡消失，气泡出现在对话里 | 保留（`answered` 本地态盖住事件到达前的空档） |
| `r6-light-anchor-jump.png`：点锚芯片后右栏横幅"正在查看历史节点 n0000 · 返回最新"，身份栏 n0000 | 保留；测试选了"非活动节点"作锚，笼项目的 n0000 是空起始模型，画面为空但流程正确 |
| `r6-light-quote-chip.png`：草稿"看看 [anchor …] 附近的密度"上方出现引用芯片 `锚 n0000 O1 ×`；移除后文本"看看 附近的密度" | 保留 |
| `r6-light-settings.png`：项目设置多出"知识模式 完整 ▾"与"结构类别 未声明 ▾" | 保留 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 提问卡解析（JSON / 非 JSON 退化 / 选项上限 / 空围栏）、`[prior]` 回复文本、"仍未回答"规则（用户答了 / Agent 自己接着说 / 仍在流式 / 从未问过） | `ui/src/lib/askCard.test.ts`（12） |
| 回执：乐观 → eid → submitted；failed 保留气泡与错误；按 eid 而非最近；无 eid 退回最近未回执插话；回放同态且不成单独行 | `ui/src/state/threadReducer.receipt.test.ts`（5） |
| 锚跳转：ASU 原子优先 / 对称像按算符 / 退回 / 不在场景；立即选中 / 等新节点场景 / 换看别的节点丢弃 / 未知标签 | `ui/src/state/crystalReducer.select.test.ts`（7） |
| 草稿芯片：列出每个锚；移除连带一侧空格 | `ui/src/lib/anchorTokens.test.ts`（5） |
| 服务端回执：submitted / failed 保留原话与错误 / 空闲无回执 | `tests/test_steer_receipt.py`（3） |
| 模板 v40 预算与牙 | `tests/test_agents_md.py`、`tests/test_upgrade_instructions.py`、`tests/test_pa2_tool_fixes.py` |

### 测试基线

- vitest 342（39 个文件）；tsc 干净；`npm run build` 2026-09-06 04:06（受管重启，health 200）。
- pytest 工作台子集 132 passed；全量 pytest：2489 passed / 26 skipped / 0 failed（10 min 10 s，2026-09-06 04:33）（`workdir/pytest-full-r6.log`）。
- Playwright r3-r6：2 passed。
- **真实提问卡（非夹具）**：`workdir/ui-evidence/r3-r6-live/glm2-ask-card-before-answer.png` - 2026-09-06 09:26，z-ai/glm-5.3 @ high（OpenRouter）在 r6-mof-ask-glm2 真实运行中按 AGENTS 格式发出的提问卡（问投料配体，四行齐全），停靠在输入框上方并带三个选项；09:27 用主人 09-05 简报原话作 `[prior]` 答复后 Agent 记入 `set_investigation`。这是 R6 交互机制第一次在真实线程里被模型自发触发的截图证据。
- 实机：交互实验一格三次预热失败（`stream disconnected before completion`，04:10 / 04:14 / 04:18），按主人指示暂停，待 API 恢复复跑。
- tag：`r3-r6-done`。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r6 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\reg12-cage\pe8f898bd' npx playwright test e2e/r6-interaction.pw.ts
```

## 第三轮 R7（2026-09-06）：子代理三选一 + 分析页电子数口径

- **真实 R7 格截图（GLM，非夹具）**：`workdir/ui-evidence/r3-r7/flash-cage-ask-card.png`（A1 的提问卡，Flash 自发，JSON 体）、`flash-cage-off-delivered.png`（A1 诊断交付）、`flash-cage-agg-ask-card.png`（A2 提问卡：In/Cd/Sn/Sb 四选一）、`flash-cage-agg-delivered.png`（A2 续接线程交付）、`glm53-hsl-off-delivered.png`（B1 发表级交付，7 min）、`glm53-hsl-agg-delivered.png`（B2：五次委派的裁决表在对话里）、`flash-cage-agg2-delivered.png`（A2′）。

复盘：`docs/reg1-2026-09-04/R3-R7-draft.md`（机制）与 `docs/reg1-2026-09-04/R3-R5-draft.md` §7（顺带修复）。前端本轮：权限菜单里的"只读审计子代理"从开关变成三选一（最高档提示（默认）/ 最高档主动委派 / 关闭），状态行按层级说明（关闭 / 当前档位未开启 / 已开启：五个角色）；分析页孔道块的"重算掩膜电子 · 精修掩膜快照"一行在重算未收敛时加"重算未收敛，以精修掩膜快照为准"（`data-recount` = ok / disagree / unconverged）。

### 提交与证据轮

- `54fcd20` R7 机制（策略 / 层级 / 模板变体 / 契约 / UI）；顺带修复提交见 §8 变更记录。
- 证据轮 **r3-r7**（`workdir/ui-evidence/r3-r7/`，8 张，复用 `e2e/r6-interaction.pw.ts` 于 Zr6 笼项目 pe8f898bd，2 passed）。
- 证据轮 **r3-anom**（`workdir/ui-evidence/r3-anom/`，6 张，`e2e/r5-analysis.pw.ts` 于 r4-mof，2 passed）。

### 观察

| 看到的 | 处理 |
|---|---|
| `r3-r7/r6-light-settings.png`：设置菜单"只读审计子代理 最高档提示（默认）▾"，状态行"当前档位已开启：角色 chemistry / density / refinement_strategy / space_group / validation" | 保留 |
| `r3-anom/anom-analysis-pores-light.png`：孔道块 "V1 16996 Å³ · 3-D 网络 · LCD 11.5 Å · PLD 8.2 ± 0.33 Å · 沿 a/b/c 6.2/6.2/8.2 Å · 419 e"，下一行 "重算掩膜电子 419.3 e/胞 · 精修掩膜快照 591.6 e/胞 ⚠"（修复前同一行是 1193.2 vs 591.6） | 保留；⚠ 这次是真的模型不同（n0109 是 SHELXL 之后的模型，快照算于 n0108），读法按规则以快照为准 |
| 同图查看器："非对称单元（长满）" + 药丸"周期截断"，647 原子 | 保留 |

### 自动守卫（本轮新增）

| 守卫 | 位置 |
|---|---|
| 委派层级真值表（策略 × 档位）、五角色集合、aggressive 变体与预算 | `tests/test_codex_agent_roles.py`、`tests/test_agents_md.py`、`tests/test_upgrade_instructions.py`、`tests/test_structure_class_setting.py` |
| 判词契约（角色文件 = 专长表、字段齐全、`parse_verdict` 不补造） | `tests/test_subagent_contract.py`（4） |
| 反常散射项：Sasaki 值与引擎一致、重建 / checkout 带项、重算记项与序列 | `tests/test_anomalous_terms.py`（3） |
| hex n0024：带项成功掩膜 / 不带项仍是诊断过的失败 | `tests/test_mask_bypass.py` |
| 未收敛重算的读法 | `tests/test_analyze_packing.py` |

### 测试基线

- 全量 pytest 2509 passed / 26 skipped / 0 failed（10:48）（`workdir/pytest-full-anom.log`）；R7 机制提交时 2505 / 26（`workdir/pytest-full-r7.log`）。
- vitest 342（39 个文件）；tsc 干净；`npm run build` 2026-09-06 05:04（受管重启，health 200）。

### 复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r7 CP_E2E_PROJECT='H:\CrystalPilot-campaigns\reg12-cage\pe8f898bd' npx playwright test e2e/r6-interaction.pw.ts
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3-anom CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r4-mof' CP_E2E_TAG=anom npx playwright test e2e/r5-analysis.pw.ts
```
