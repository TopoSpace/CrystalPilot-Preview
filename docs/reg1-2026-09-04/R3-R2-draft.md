# 第三轮 R2 复盘（2026-09-05）：视觉层：主会话栏（R2-A）与侧栏 / 查看器（R2-B）

> 计划：`docs/PLAN-2026-09-05-round3.md` §3 R2（含主人追加的"主会话栏也要简洁、高级、少视觉污染、适当动效"）。tag：`r3-r1-done` → `r3-r2-done`。
> 提交：`6c2ff94`（MCP 启动探针与首回合就绪等待）、`26065ac`（R2-A 主会话栏）、R2-B 侧栏/查看器提交（见 `git log r3-r1-done..r3-r2-done`）、本文档提交。
> 证据：`workdir/ui-evidence/r3-r2a/`、`workdir/ui-evidence/r3-r2b/`（小分子）、`workdir/ui-evidence/r3-r2b-mof/`（Zr-MOF 演示，225 节点）、`workdir/ui-evidence/r3-r2b-cage/`（Zr6 笼，189 节点）。

## 一、修好了什么

### R2-A 主会话栏（`26065ac`）

三级信息层级：L1 全权重（用户消息/插话、Agent 中文说明、提问/审批/交付卡、回合分隔），L2 紧凑可折叠（工具行、命令行、自动审批、推理摘要），L3 按需（参数/结果原文）。

| 项 | 做法 |
|---|---|
| 状态行 `StatusRail` | 取代计数版阶段轨、头部"运行中"徽章和浮动药丸：左侧阶段只画 ✓ / ● / ○（计数进 tooltip，窄屏横向滚动），右侧一条动作行，呼吸星标 + 当前工具人话 + 已用时 + "可插话"；等待审批 / 上次回合失败 / 中断 / 空闲各一种；空闲写"空闲 · 上次回合 mm:ss · 节点 nXXXX"。shimmer 超过 5 分钟自动静音，计时继续。纯模型在 `lib/statusRail.ts`（vitest）。 |
| 工具行 `ToolCard` | 一行 = 字形 · 人话标题 · 结果一句话（芯片改成文字）· 用时；展开才有芯片/告警/正文/技术详情，原始 JSON 再深一层。失败行同一行式：红字形 + 3 px 左侧色条 + 原因行内，不再整卡红边。 |
| 审批 | 自动通过的审批在"简洁"里不再单独成行（与工具行重复），"详细"里可见；折叠标签在简洁模式不计审批数。 |
| 交付卡 `DeliveryCard` | 状态芯片（定稿 / 暂定 / 诊断性）+ 豁免数 + 节点 + write_outputs 的 R1/wR2/GooF + 五个主文件链接 + "全部 N 个文件 → 产物页签"（过滤 `command_output/` 与 `transcript.jsonl`）；右栏按 `cp:right-tab` 事件切页签。 |
| 滚动与尾行 | 读者上滚后出现"↓ 回到最新"；运行中的尾行显示当前动作 + 已用时。 |
| 动效目录 | 行淡入 120 ms、字形交叉淡入 150 ms、阶段软脉冲 2.4 s；不做整卡扫光；`prefers-reduced-motion` 全局静态。 |

附带修的两个 MCP 问题（`6c2ff94`，服务器重启后线程续跑时暴露）：codex 的 `resources/templates/list` / `prompts/list` 探针在我们的 MCP 上返回 -32601，agent 由此认为工具没了，现在与 `resources/list` 一样返回空表（`tests/test_mcp_probes.py` 驱动真实 stdio 服务器）；codex 在 `thread/start` / `thread/resume` 后异步起 MCP、回合立刻开始，首次模型调用早于工具注册就只剩 shell - turn worker 现在在新建/续接会话的第一回合前等待工具注册（有界：75 s，服务器根本不在列表时 20 s），等待过程以 `mcp_startup` 系统行（正在启动… / 已就绪 N 个工具 · s / 超时）同时落 transcript 与推送（`tests/test_mcp_ready_wait.py`）。实机核对：重启后续接线程的第一回合调用了 `situation_report`，38 s 后空闲。

### R2-B 侧栏与查看器（结构为主体）

| 项 | 做法 | 证据 |
|---|---|---|
| 相机 | `fitNow()` 只对原子取包围球：3Dmol 的 `zoomTo()` 只有在选择为空时才把形状（晶胞框、孔道面、对称元素）算进包围球，改成匹配全部原子的非空选择即可；纵横比回退保留。选中原子卡新增"居中"（单原子 `zoomTo` 300 ms 动画，5 Å 最小球 = 该原子及其第一配位壳），"重置视角"回全景。 | MOF：n0224 的 Zr2 簇 + 配体撑满画布（此前 39 Å 胞里只剩画面中央一小团）；`*-centered.png` |
| 范围 / 生长菜单 | 按 Olex2 分两组并加组标题：**范围**（非对称单元 `fuse` / 晶胞 `pack cell` / 超胞 2³ 3³ 4³ `pack 0 n` / 半径 8、16 Å `pack r` / 分数盒 `pack -0.5 1.5`）、**动作**（长一层 `grow -s` / 扩展至 4 层 / 补全 `grow -w` / 收回 `fuse`（长过才出现）/ 装配 `compaq -a`）；"范围 −0.5…1.5"改叫"分数盒"以免与组名重名；＋生长按钮仍在菜单外。 | `*-extent-menu.png`；`CrystalToolbar.test.ts`（顺序、组标题、收回落在补全之后） |
| 主题 / 字号 | 浅色 `ink-2 #5c574f → #504b44`、`ink-3 #6b655c → #605a52`（raised 上 4.6:1 → 5.5:1），深色 `ink-3 #a39e93 → #a7a297`（4.96 → 5.2）；`theme.test.ts` 新增 ink-2/ink-3 在 bg/surface/raised 上 ≥ 5:1 的守卫（两主题）；`ShellCurve` 的 8 / 8.5 / 10.5 px 硬编码改 `text-2xs` 令牌（11 px 下限），留白同步放大。 | vitest；Playwright 断言 `--color-ink-3` 令牌值 |
| 左栏 | 项目显示名：`settings.display_name`（左栏项目行悬停"改名"，`POST /api/projects/settings`，写进项目设置，左栏 / 状态板 / 打开对话框 / 首页一起变）→ `context.json` 的 `title` → 目录名；最近项目列表把 UI 自建的 `ui-import-<时间戳>` 和用户手动"隐藏"的项目折进"更多 N"（隐藏是浏览器本地偏好 `cp.hiddenProjects`，说的是"我不想看"，不是项目属性，所以不进项目设置）。 | 截图左栏；`tests/test_project_display_name.py`；`hiddenProjects.test.ts` |
| 身份栏 | 两行固定栅格：行 1 节点芯片 · 分支（先让步，title 全名）· 空间群（Olex2 的右上斜体）· 引用 · ▶；行 2（折叠时）化学式（title 全式）· R1/wR2/GooF · 原子/键/多面体（容器 < 480 px 时让位，范围药丸与展开卡仍有）。 | Playwright：两行 `scrollWidth ≤ clientWidth`，每个 `.truncate` 都带 `title` |
| 节点树 | 纯模型 `lib/nodeTree.ts`：每条分支一行可折叠的分支头（名称 · 当前 · N 节点；折叠时带头节点与 R1），`diag/*` 家族收成一行"诊断分支 · N 条 · M 节点"（默认收起），git 车道按**可见行区间 + 分叉落点**打包并复用（28 条分支不再是 28 列）；每个节点写 R1 来源，自己精修的正常显示，未精修的显示"R1 x.xxxx · 沿用 nXXXX"（最近一次精修的祖先）；三种标记：当前查看（行高亮 + aria-current）、已交付（读结果目录 `MANIFEST.json`：定稿 / 暂定 / 诊断性三种色调，tooltip 列出交付目录）、R1 最优（不含诊断分支）。分支对比表默认收起、不含诊断分支、沿用值打 `*`。 | MOF：45 条非诊断分支 3–4 条车道；cage：72 条诊断分支 / 153 节点收成一行；`nodeTree.test.ts`（7） |
| 聚焦模式 | 右栏顶部图标：右栏 ≥ 64% 窗宽（拖得更宽者胜，对话 ≥ 320 px），左栏变抽屉；状态进 URL（`?focus=1`），Esc 退出（有菜单打开时 Esc 先关菜单）。 | `*-focus.png` 三种宽度 × 两主题 |
| 产物页 | 按交付目录分组（顶层交付 / `guest-location-update` / `whole-guest-study` …），组头 = 目录 · 状态芯片 · 节点（来自 MANIFEST）· 文件数；主文件（CIF / FCF / RES / SUMMARY / VALIDATION）在前，其余藏在"全部 N 个文件 (+k)"；命令输出等运行日志单独折叠；路径一律 `/`，行内只显示文件名，全路径在 title。 | `*-artifacts.png`；`artifactGroups.test.ts` |
| 服务端 | `GET /api/wb/refine/nodes` 带 `deliveries`（扫描 `CrystalPilot Results/*/MANIFEST.json` 与一层子目录，旧格式无源节点的跳过；`limit` 100 → 400）；`/api/projects/recent`、`/api/projects/status`、`/api/projects/settings` 带 `display_name`；`update_project_settings` 接受 `display_name`（折叠空白、80 字上限、空即清除）。 | `tests/test_project_display_name.py`（7） |

## 二、验证了什么

### 自动测试

- vitest 312（34 个文件；R2-A 前 295）；`tsc` 干净；`npm run build` 通过。
- 服务端相关 pytest：`test_project_display_name.py` 7 + `test_structure_class_setting.py` + `test_server_routes.py` 共 43 通过。全量 pytest：2368 passed / 25 skipped / 0 failed（2026-09-05 23:07，10 min 54 s，仓库外 basetemp，`workdir/pytest-full-r3r2.log`；R1 时 2355）。
- Playwright `e2e/r2b-layout.pw.ts`：6 用例（3 种窗宽 900 / 1100 / 1440 × 浅深两主题）在**三个真实项目**上全部通过，`r3\r1-org-hsl-2`（小分子，14 节点，本轮改名为"小分子 org_hsl · R1 实机验证"）、`live-demo-20260905-1503\mof`（Zr-MOF 演示，225 节点、45 条非诊断分支 + 6 条诊断分支）、`reg12-cage\pe8f898bd`（Zr6 笼，189 节点、72 条诊断分支）。每个用例的断言：`--color-ink-3` 是新令牌值；身份栏两行不溢出、截断元素都带 title；范围菜单组标题恰为 ["范围","动作"]、首项非对称单元、末项装配、"长一层"在"分数盒"之后；ADP 徽章选中真实原子后"居中"可点；节点树有分支头、诊断行 `aria-expanded=false`、图 SVG 宽度小于半个面板、折叠首条分支后节点行减少、再展开恢复、`aria-current` 的节点恰一行；产物页有分组且屏上无反斜杠路径；聚焦后右栏 ≥ 60% 窗宽、对话列 ≥ 300 px、Esc 后 URL 不含 focus；≥1200 px 时左栏有项目名且主列表无 `ui-import-*`；无页面错误。
- 全套 Playwright（既有用例回归，含 300 px 侧栏 × 13/16 px 字号的菜单几何与字号下限）：25 passed / 4 skipped（跳过的 4 个为缺结构文档夹具与进度传输夹具的既有用例，与 r3-pre 基线相同；含 300 px 侧栏 × 13/16 px、visual-review 三宽 + 深色、workbench 生长/超胞、reconnect 三例）。

### 我看过的截图（视觉复核）

| 截图 | 看到的 |
|---|---|
| `r3-r2b/1440-light-thread.png` | 左栏"小分子 org_hsl · R1 实机验证"+ 状态行，最近项目里没有 ui-import，"更多 21"；身份栏两行完整；状态行"空闲 · 上次回合 00:29 · 节点 n0013"；分子撑满画布，晶胞框只在四角露出 |
| `r3-r2b/1440-light-nodes.png` | 三条分支头（orthorhombic-solution-trial 当前 9 节点 / residual-split-diagnostic 4 节点 / main 1 节点），n0013 带"当前 已交付 ✓R1 最优"，未精修节点写"R1 0.0263 · 沿用 n0007"，两条车道 |
| `r3-r2b/1440-light-focus.png` | 右栏约 64%，左栏收起，对话列仍可读 |
| `r3-r2b/1100-light-extent-menu.png` | "范围"8 项 / "动作"3 项 + 装配，各带 Olex2 命令 |
| `r3-r2b/900-dark-artifacts.png` | "顶层交付 · 定稿 · 节点 n0013 · 11 个文件"，五个主文件，"全部 11 个文件 (+6)"，"运行日志 4 个文件" |
| `r3-r2b-mof/1440-light-thread.png` | Zr-MOF：n0224 的 Zr2 簇 + 对溴苯乙酸配体撑满画布（相机修复的直接证据）；身份栏化学式截断但 title 有全式 |
| `r3-r2b-mof/1440-light-nodes.png` | 45 条非诊断分支折成分支头，3–4 条车道；n0224"当前 已交付"；`hypothesis/pBrAc-Br-average-mirror` 10 节点里 9 个写"沿用 n0219" |
| `r3-r2b-cage/1440-light-nodes.png` | "诊断分支 72 条 · 153 节点"一行收起；`(detached from n0181)` 之类的一节点分支各一行 |
| `r3-r2b-cage/1440-dark-thread.png` | 笼的 Zr6 簇与配体填满画布宽度，晶胞框在右下露出一角 |

### 观察到但本轮没改的

- 1440 px 下默认右栏 432 px：身份栏行 2 的化学式在长式（C12.67H6Br0.15O6.08Zr2）下仍会截断，全式在 title；把"原子/键"计数的显示阈值提到 480 px 后化学式能多占一截。
- 主会话栏失败行的原因仍是工具返回的英文原话（"BR1G is already in PART −1…"），要等 R3 WP1 的结构化错误再中文化。
- Zr-MOF 演示线程里 codex 仍为同一线程起两个 MCP 进程（R1 已把它变成非致命）。

## 三、没做什么（如实边界）

| 计划项 | 状态 | 说明 |
|---|---|---|
| Mode Grow：短接触 / 范德华 / 选中原子的对称像 | 未做 → R5 | 需要 `refine/scene.py::build_scene` 服务端算候选键（`grow_mode=short|vdw|selection`）；现有"生长键"图层（点击即生长）保留 |
| "长满"= Olex2 `grow` 直到对称算符重复、超预算标"已截断" | 未做 → R5 | 菜单里仍是"扩展至 4 层"并如实标注"不保证有限分子完整" |
| 晶胞框变成"视图"面板里的可关图层 | 未做 | 晶胞框仍常显；相机已不再被它主导 |
| 节点落地时对话里与右栏的节点芯片同时闪一次 | 未做 | R2-A 动效清单里的联动项 |
| 输入框模型/档位做成 Codex 式选择器 | 已有 | "6 Astra · 极高 ▾"本来就是选择器；运行中"■ 停止"键也已存在 |
| 节点树折叠状态跨会话记忆 | 部分 | 诊断家族开关持久化（`cp.sect.nodes.diagOpen`），单条分支的折叠只记在会话内 |
| 项目改名 | 有条件 | `POST /api/projects/settings` 要求项目已打开（沿用原路由），未打开的项目暂不能从"最近项目"里改名 |

## 四、复现

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r2b CP_E2E_PROJECT='H:\CrystalPilot-campaigns\r3\r1-org-hsl-2' npx playwright test e2e/r2b-layout.pw.ts
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r2b-mof CP_E2E_PROJECT='H:\CrystalPilot-campaigns\live-demo-20260905-1503\mof' npx playwright test e2e/r2b-layout.pw.ts
```

```bash
cd ui && CP_EVIDENCE_ROUND=r3-r2b-cage CP_E2E_PROJECT='H:\CrystalPilot-campaigns\reg12-cage\pe8f898bd' npx playwright test e2e/r2b-layout.pw.ts
```

```bash
cd ui && npx vitest run
```

```bash
.venv/Scripts/python.exe -X utf8 -m pytest -q tests/test_project_display_name.py tests/test_mcp_probes.py tests/test_mcp_ready_wait.py -p no:cacheprovider --basetemp=C:/tmp/claude/cp-pytest-tmp/r2
```
