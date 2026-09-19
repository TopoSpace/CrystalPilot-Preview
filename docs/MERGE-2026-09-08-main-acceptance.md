# 2026-09-08：main 合并 Copilot 分支与 H 盘运行环境验收

> 交接来源：分支 `topospace-crystalpilot-system-review`（已验收提交 `c4f0523`，工作树在 D 盘 `copilot-worktrees\CrystalPilot\topospace-vigilant-couscous`），Copilot 的说明见 `docs\UPGRADE-2026-09-08-workbench.md`（§11–12 为最终收尾）与 `docs\PROVIDERS-2026-09-07.md`。本文记录合并、在 H 盘发现并修掉的问题、环境与工具核验、隔离冒烟、以及正式 8010 的迁移与回退。

## 1. 合并结果

| 项 | 结果 |
|---|---|
| 合并前 main | `0f5848f`（也是分支的 merge-base，0 ↔ 31，可快进） |
| `git merge --ff-only` | 成功 → `c4f0523`，163 文件 / +13300 / −1436 |
| 合并后修复提交 | `67c4798`（导入后重复解析反射文件的回归）、`bdfbbec`（旧节点几何孔道 + 13 个随分支带进来的失败测试） |
| 工作区 | 仅 `codex-home/config.toml` 有主人自己的一条 trust 条目，保留；后续与本次批准的配置改动一起提交 |
| 未删除 | D 盘 worktree、`.claude/worktrees/sad-dhawan-0751f5`、任何锁 / journal / 数据版本 |

Copilot 这轮的实质（细节在其 UPGRADE 文档）：结构⇄分析检查器联动、动效/会话状态一致化、checkCIF 短路径运行时 + Job Object 清理、跨进程项目锁与节点发布事务（R1）、顾问子代理只读快照、SHELXL 参数/反射计数真值、**受控反射数据版本（`.crystalpilot\refine\data\dNNNNNN`，节点与观测分开绑定）**、只读比较 API 与前后比较 UI、提供方配置升级（密钥只写 `secrets/`）。

## 2. 合并后在 H 盘发现并修掉的问题（17 个失败测试，全部在分支自己的 D 盘工作树上同样失败）

Copilot 最终验收只跑了 149 个后端测试；全量 2672 个里有 17 个在 `c4f0523` 上就是红的。逐个查明：

**A. 真回归（1 个，`67c4798`）**：受控导入先解析暂存目录里的 HKL，再把同一份字节发布成不可变数据版本（新路径、新 mtime）。解析缓存按 路径+mtime+大小 取键，于是**每次导入后的第一次 checkout 都把整个反射文件重新解析并重新合并**（337k 行 MOF 数据 0.65 s，正是缓存要省掉的那笔）。现在暂存阶段结束且已提交时把解析/合并缓存改键到发布后的文件。

**B. 旧节点孔道产品缺陷（1 个，第三个提交）**：`build_void_ccp4` 重建会话时没传 `allow_unbound`，于是 09-08 之前的每个项目在"分析"页签的孔道块都以 `DataBindingRequired` 报错、什么都不显示。§11 的承诺恰恰相反，旧节点几何可用、只有反射派生量未知。现在未绑定节点走与纯 CIF 节点相同的几何孔道路径（按模型取缓存键），`voids.json` 用 `binding_required: true` 与 `electron_count_status: "binding_required"` 说明电子数为什么缺。

**C. 测试与新规则不一致（15 个）**：旧夹具项目（`demo-live-sjtu9`、`pa1/hex-l2-r1`、`mvp-sjtu9`）的节点没有 `data_revision`，所有反射工具按规则拒绝。测试改为**像用户一样**通过 `swap_reflection_data(model_node=…, hkl="crystal.hkl", reason=…)` 显式绑定（`tests/helpers_binding.py`），而不是绕过存储改 node.json；裸 NodeStore 的掩膜诊断树补上最小数据版本与"已完成测量"标记（指标只有对着绑定数据版本的测量才算 current）；失败的工具调用会从已发布节点重建会话，所以撤销测试重新读取 `p.session`；无原子定群的测试替身补上 `.dir`；`source_state()` 多出的 `data_revision`、数据块路由对旧节点回答 `unavailable`（而不是拿当前 HKL 冒充历史）也各自更新了断言并补了绑定节点的正向用例。

**主人须知（行为变化，不是我改的，是分支的设计）**：09-08 之前创建的项目（`usertest/test1-0906`、`test2-0907`、`r3/*` 等）的节点全部是"旧节点"：打开、看几何、分析页签、引用都正常，但**精修 / 掩膜 / SHELXL / 孪晶 等一切反射计算会被拒绝**，直到在该项目里用 `swap_reflection_data(model_node=<节点>, hkl="crystal.hkl", reason="…")` 明确绑定一次（会生成一个新的已绑定子节点，旧节点与旧指标不改写）。`get_project_brief` 会把这个状态和这条命令直接告诉模型。

另一个值得知道的语义：**任何失败的工具调用都会丢弃并从磁盘重建会话**（保证半成品不残留）；大 MOF 上一次被拒绝的调用因此多花 1–2 s。

## 3. H 盘运行环境核验（不以网页能打开代替）

| 项 | H 盘实测 | 备注 |
|---|---|---|
| Python | `.venv` 3.12.4；从中性 cwd `import crystalpilot` → `H:\CrystalPilot\crystalpilot\__init__.py`（editable 安装） | D 盘 venv 指向 D 盘自己的源码，两边互不串 |
| cctbx / smtbx / iotbx | 2025.11 | |
| gemmi / RDKit / psutil | 0.7.5 / 2026.03.5 / 7.2.2 | 分支把 `psutil>=5.9` 加进 `workbench` extra；已满足 |
| mcp / openai-codex SDK | 1.x / 0.147.0 | pyproject 钉 0.147 |
| **Codex 内核** | **npm 0.153.4**（`vendor/codex`，`/api/kernel` 报 `source: npm`） | **D 盘 worktree 没有 vendor/codex，Copilot 这轮全部跑在 pip 0.147 内核上**；H 盘从 09-07 起就是 0.153.4 |
| MCP 工具面 | 对真实项目 `refinement_registry(project)` = **74** 个工具 | |
| SHELXL / SHELXT | 2019/3、2018/2，可执行 | `vendor/shelx/`，含 salflibc / wgxlib01 / wgxlib04 三个 DLL |
| PLATON + SHELXL + DLL | opt-in 真二进制测试 `test_real_platon_publication_cif_long_project_path` 用 `sol-small-cold` 的真实 final.cif（复制到临时目录）**11 s 通过**：短路径运行时、进程树清理、完整报告门槛 | |
| ciftab / superflip | 存在；superflip 可执行（无参数时要输入文件名） | |
| DIALS（原始帧） | conda 环境 `C:\Users\username\miniforge3\envs\dials` 被 `find_dials()` 找到 | 未跑真实帧 |
| Systre（拓扑命名） | `vendor/gavrog/Systre-19.6.0.jar` + Java 17 在 PATH | 全量 pytest 的拓扑已知答案用例覆盖 |
| olex2c | `vendor/olex2/app/olex2c.dll` 存在 | `test_olex2_tool::test_help_boot` 在并发负载下超时（老问题），单跑通过 |
| CrysAlisPro（CAP） | `C:\Xcalibur` 存在；未启动、未验证 | 主人本机厂商 GUI，只报告存在 |
| Playwright | 1.62.1 + 浏览器 | |

与 D 盘 venv 的差异：D 盘多 `sse-starlette`、`ruff`，numpy/pydantic/rdkit 小版本略新；代码只 `import anyio`（两边都有），声明依赖 H 盘全部满足。没有复制虚拟环境。

## 4. 测试与隔离冒烟（H 盘，均为本机新跑；D 盘的通过不计）

| 组 | 结果 |
|---|---|
| tsc / vitest / build | 0 error / **50 文件 529 passed** / 通过（`ui/dist` 重建，`built_at 2026-09-08T11:19:25Z`） |
| 分支改动的 26 个测试文件 + 服务器/模板测试 | 修复前 432 passed / 4 failed；修复后相关组 98 passed |
| 13 个遗留失败对应的文件组 | 83 + 94 + 32 passed |
| 全量 pytest 第一遍（合并态、修复前） | 2654 passed / 18 failed / 27 skipped（32 min，与 UI 测试并行） |
| 全量 pytest 第二遍（修复后，`bdfbbec`） | **2672 passed / 27 skipped / 1 failed**（21 min 34 s）；唯一失败是守 config.toml 默认模型的 `test_model_defaults`，因主人批准的默认改为 gpt-5.6-sol 而红，随即改为新默认（单跑 5 passed） |
| 8011 隔离冒烟（真 H 盘 codex-home / vendor / venv，`CRYSTALPILOT_CPU_CORES=2`） | `/api/health ok`；`/api/kernel` 0.153.4 npm；两家提供方 `has_key=true`；从 H 盘凭据实际列出网关 21 个模型（仅目录，无推理）；打开外部验收项目 → nodes / scene / comparison / data（`source=node, d000001, R_int 0.0117`）/ threads 全 200；子进程确认是 `H:\CrystalPilot\vendor\codex\…\codex.exe`，MCP 命令指向 H 盘 venv |
| 8011 浏览器 | **22 passed / 0 failed**：Copilot 的 12 项生产 oracle/比较用例 + providers 3 + appearance 3 + health + 相机深度 2（ZIF-8 纯 CIF 项目）+ feed 重连 1 |

冒烟里唯一的异常：**服务启动后的第一次 `projects/open` 用了 145.7 s**（当时全量 pytest 与 Playwright 同时在跑、服务限 2 核 BelowNormal），随后同项目再开 0.2 s、从未开过的项目 1.2 s。归因为进程内首次装载整个工具栈的冷启动被 CPU 争用拉长，没有复现；正式 8010 用 4 核。

没有做的：没有调用任何模型；没有改任何真实科学模型；复制过来的 codex 会话记录能否续接要到第一次真实发送才知道。

## 5. 正式 8010 迁移（已完成，2026-09-08 21:05；主人批准：全量 pytest 通过后迁移、改用 D 盘界面里输入的密钥、默认模型改 gpt-5.6-sol @ xhigh）

**准备（服务仍在 D 盘时做，只动 H 盘）**：D 盘 5 个 codex 会话记录复制进 `codex-home/sessions/2026/09/07|08/`（sol-mof-diagnostic、sol-small-cold、sol-cage-cold、test3-1-0908、test3-2-0908 的线程）；D 盘 12 个最近项目并入 `workdir/projects.json`（上限 30，H 盘最老 7 个掉出列表）；D 盘 `secrets/crystalpilot.txt`、`secrets/openrouter.txt` 复制进 H 盘 `secrets/`（原 openrouter.txt 备份为 `openrouter.txt.bak-20260906`；只复制文件，内容未显示）；`codex-home/config.toml` 网关认证改为 `--cred H:\CrystalPilot\secrets\crystalpilot.txt`、`model = "gpt-5.6-sol"`（tomllib 解析通过，两家提供方 `managed_api_key / has_key=true`）。回退脚本 `workdir/services/rollback-8010-to-D.ps1` 先写好。

**切换**：
- 21:05:14 停止 D 盘服务：先确认无运行中回合（test3-1-0908 / test3-2-0908 打开但空闲，主人当场确认"现在切"），再按 **PID 56892**（2026-09-08 15:42:53 启动、父进程 powershell 51852、命令行含 D 盘 worktree 路径，三项在同一条命令里核对后才执行）`taskkill /T`，整树（listener 45600 及其 app-server / MCP 子进程）退出，8010 空闲。
- 重同步会话记录：test3-1-0908 的 rollout 在 20:00 首次复制后又增长（27.3 → 28.4 MB，主人期间跑过一个回合），按"新者覆盖"再同步一次。
- 21:05:35 `scripts/restart_server.ps1` 冷启动：launcher **PID 38920** → listener **PID 52892**（21:05:38），`H:\CrystalPilot\.venv\Scripts\python.exe -X utf8 -m uvicorn server.app:app --loop asyncio:SelectorEventLoop --port 8010`，4 核 BelowNormal，日志 `workdir/uvicorn_r13.log` / `uvicorn_r13.err.log`，PID 文件 `workdir/uvicorn_r13.pid`。

**验证（对正式 8010）**：`/api/health ok`、`ui_build.stale=false`；`/api/kernel` 0.153.4 npm，路径 `H:\CrystalPilot\vendor\codex\…\codex.exe`；`/api/providers` 两家 `managed_api_key / has_key=true`，默认 crystalpilot；用迁移后的网关凭据列出目录 22 项 / 21 项可用，gpt-5.6-sol 可用（仅目录列表，无推理）；最近列表 30 条、D 盘 12 条在前；打开 test3-1-0908（102 节点、1 线程、transcript 2000 条 / 6 个回合）0.3 s、test3-2-0908（78 节点）2.1 s，transcript 可读；listener 的 app-server 子进程全部是 H 盘 codex.exe，MCP 命令指向 H 盘 venv；Playwright `health` + `feed-reconnect` 对 8010 2 passed。

**未验证**：复制过来的 codex 会话要到第一次真实发送才知道能否 resume；模型推理本身没有调用。

**回退**：`powershell -NoProfile -ExecutionPolicy Bypass -File H:\CrystalPilot\workdir\services\rollback-8010-to-D.ps1`（只按命令行停 H 盘服务，再用 D 盘 venv + `audit-codex-home` 启动，健康轮询 90 s）；配置回退用 `workdir/services/backup-20260908-premigration/`（config.toml、model_catalog.custom.json、projects.json、launch.json）与 `secrets/openrouter.txt.bak-20260906`；代码回退按提交 `git revert`（不 reset）。D 盘 worktree 原样保留，其 `workdir\services\8010\service.json` 现在记录的是已停止的 PID 45600（陈旧）。

## 6. 脱离 D 盘：证据归档与分支核查（2026-09-08 晚）

**日志/截图已归档到 H 盘**：`workdir\archive-copilot-D-20260908\`（499 文件 / 58.9 MB），目录结构与原 `workdir\` 对应，所以文档正文里写的 `workdir\round3-final-*.log`、`workdir\ui-evidence\audit-0907-*` 等路径都能在这里找到。含全部顶层 `audit-*.log|json` 与 `round3-*` 日志、`ui-evidence\`（21 组截图与 Playwright 报告）、`services\`（8010 服务记录与日志）、`round2-*` 结果、隔离 codex 配置一份。**有意未复制**：`audit-codex-home\`（除 config.toml）与 `round3-closeout-codex\`，共约 236 MB 的 codex 自身 sqlite 状态，真正有价值的 5 个会话 rollout 已在 `codex-home\sessions\2026\09\07|08\`；`audit-*-tests\`、`provider-*\` 是 pytest 临时目录。

**所有分支都已在 main 里**：仓库共 13 个分支的提交不在 main 的第一父链上，逐条核实全部是同一份工作的旧版本，9 个 topospace/astra 分支（Copilot 的子会话原件）每条提交标题都能对上 main 里的提交（`Serialize project operations…` = `5700663`、`Upgrade provider configuration` = `eee2ff4` …），4 个 `worktree-agent-*` 是第二轮副线快照；它们碰过的**每一个文件 main 都有，且 main 的版本行数等于或大于分支版本**（如 `scene.py` 快照 1780 行 / main 2304 行）。D 盘三个工作区无未提交改动。

**没有活的 D 盘依赖**：`codex-home\config.toml`、`.claude\launch.json`、`scripts\*`、`workdir\projects.json` 与全部源码/测试都不含 D 盘路径；只有本文与 UPGRADE 文档在正文里作为历史记录提到过。

### 一处真正没合并的旧工作（已按主人指示移植进 main）

`H:\CrystalPilot\.claude\worktrees\sad-dhawan-0751f5`（2026-09-01，分支 `claude/sad-dhawan-0751f5`，其提交已在 main）里有**未提交**改动，导出为 `workdir\scratch\unmerged\sad-dhawan-0751f5-uncommitted.patch`（600 行）。

内容是 **Olex2 的 IUCr 导出 CIF**：这类沉积文件既没有单独的 hkl，也没有 `_shelx_hkl_file`，而是把整份 .fcf 塞进 `_iucr_refine_fcf_details` 文本字段。main 只找 `_shelx_hkl_file`，因此导入这类 CIF 直接失败并报 "no reflection data … the CIF embeds no `_shelx_hkl_file`"。补丁加了：`cif_sf._find_refln_block`（在文本字段里找反射块，真正的 `_refln` loop 优先）、`tools_ingest._fcf_osf` / `_set_res_osf`（按写出的 hkl 改写 RES 的总标度因子，否则首轮精修从错误标度起步，且保留自由变量），以及 12 个测试。

**验证过是真东西，不是被取代的旧代码**：把该工作树的测试文件原样对 main 的代码跑，**11 个新测试里 9 个失败**（另 2 个是 main 已有的块扫描行为）。

**移植结果（2026-09-08）**：补丁不能直接套用（main 的 `tools_ingest.py` 已从 776 行长到 1056 行，且文件写入改走数据版本暂存层），按 main 的结构重写后合入：

- `crystalpilot/io/cif_sf.py`：`_EMBEDDED_FCF_TAG` + `_find_refln_block`，真正的顶层 `_refln` loop 优先，找不到才进文本字段里解析内嵌 fcf；元数据回退链改成"反射块 → 承载它的结构块 → 参考 CIF"（裸 fcf 有对称操作但常无晶胞/波长/化学式），`instrument_meta["embedded_fcf"]` 标注来源。
- `crystalpilot/refine/tools_ingest.py`：新增 `_iucr_refine_fcf_details` 反射分支（写在 `_shelx_hkl_file` 之后，fcf 是沉积精修用的**已合并**数据，不是原始测量），`_fcf_osf` / `_set_res_osf` 按写出的 hkl 改写 RES 总标度因子并保留自由变量，HKLF5 模型遇到只有 fcf 时明确报警（合并数据没有批号列，SHELXL 会拒），并把"crystal.hkl 来自内嵌 fcf、是合并数据"写进 `context.json` 的 `data.reflections`（持久证据，不只是一次性提示）。写文件路径全部改用 `input_directory(p)`，标度记进 `_input_stage.scale_applied`，与数据版本层一致。
- `tests/test_cif_datablocks.py`：15 个测试（原补丁 12 个 + 4 个真实沉积参数化）。

**验收**：该文件 26 个测试全过；相关 11 个套件 151 个测试全过；**全量 pytest 2688 通过 / 27 跳过 / 0 失败**。真实数据上，四个此前完全无法导入的沉积现在都能导入，写出的反射条数与沉积自报的 `REM Reflections_all` 一致，SHELXL `mode='check'`（只算不改）复算出的 R1 与各自发表值相差 ≤0.0013：

| 沉积 | 反射数 | 发表 R1 | 复算 R1 | 发表 wR2 | 复算 wR2 |
|---|---|---|---|---|---|
| Q.cif | 5865 | 0.2298 | 0.2291 | 0.5422 | 0.5333 |
| T2-1-cage.cif | 32064 | 0.2332 | 0.2319 | 0.5524 | 0.5445 |
| shelxt-2024-07-Cu.cif | 11896 | 0.3096 | 0.3093 | 0.6581 | 0.6501 |
| shelxt250626-La.cif | 20054 | 0.1987 | 0.1989 | 0.5397 | 0.5398 |

**一处与原补丁说法不符，如实记下**：原补丁称不改 FVAR 会让 SHELXL 报出"高得离谱"的 R1。实测把 Q.cif 的标度因子改回沉积原值再复算，R1 = 0.2292（改写后 0.2291），几乎无差别，因为 SHELXL 和 smtbx 都会自己拟合总标度（节点条件里记的就是 `fitted_overall_scale`）。所以真正解决问题的是"读到内嵌 fcf"，`_set_res_osf` 的价值是让 RES 与它旁边的 hkl 自洽（导出、或标度被固定的场合才吃紧），不是 R1 复现的前提。复算脚本：`workdir\scratch\olex2_live_check.py`。

## 7. 尚缺与后续

- 主人的旧项目需要一次显式绑定（§2 主人须知）；这是否应当有"一键绑定当前 crystal.hkl"的 UI 入口，由主人决定。
- Copilot 在 pip 0.147 内核上验收，H 盘运行 npm 0.153.4；本次 22 项浏览器用例与 API 冒烟在 0.153.4 上通过，但"子代理 / 压缩 / 线程恢复"等内核功能在合并后的代码上还没有真实回合证据。
- `test_olex2_tool::test_help_boot` 仍是负载敏感的老抖动。
- 最近项目列表上限 30：并入 D 盘 12 个后，H 盘最老的 7 个（r1-org-hsl-2、pe8f898bd、r4-mof、r6-mof-ask-b、r6-mof-ask、live-demo mof、r1-org-hsl）从列表掉出，磁盘未动，可从"打开项目"重新打开。
- D 盘 worktree 未归档、未删除；其 8010 服务按主人批准停止。
