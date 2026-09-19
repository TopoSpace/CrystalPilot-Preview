# 2026-09-16 批次报告：稳定性 · 工具卡终态 · Logo · 存储治理 · 性能 · 同步私有仓

范围：仓库 `H:\CrystalPilot`（app-server 内核 npm codex 0.154.0，`vendor/codex`；隔离的
`codex-home/`）。所有回归都跑在 `H:\cp-pytest-tmp\` 下的副本上（主要是 `handover-real\test3-2`，
线程 `01a0800b-76d3-7451-b47f-8b4db4507a32`），用户的真实项目目录只读。

配套：`docs/OPTIMIZATION-BACKLOG-2026-09-16.md`（全景审视三档清单）。

---

## 一、根因与证据

### 1a 页面卡住、不刷新就不再更新

四个相互叠加的根因，全部在传输层，与模型无关：

1. **EventSource 收到非 2xx 就永久关闭。** 服务器重启后的头几秒、或项目尚未打开时，
   `/api/wb/sse` 返回 400/404，浏览器把 `readyState` 置为 CLOSED，之后**永不重试**（浏览器只在网络层
   中断后自动重连）。页面看起来一切正常，但再也收不到事件。证据：`workdir/uvicorn_r13.log` 里
   重启后成串的 `GET /api/wb/sse ... 400`，之后再无同一客户端的重连。
2. **闲置回收让旧通道静默失效。** `WorkbenchPool` 在项目闲置 30 分钟（`IDLE_SHUTDOWN_S`）后关闭
   `ProjectSession`，其 `Channel` 被丢弃；仍连着的浏览器不会收到任何东西，服务器端的 SSE 生成器
   卡在 `read_since` 上，直到 TCP 层面超时。
3. **没有心跳检测。** 原来的保活是 SSE 注释行 `: keepalive`，对 JavaScript 完全不可见，前端无法判断
   "安静"是真的没事还是已经断了。
4. **同步生成器占线程池名额。** `_sse` 是同步 `def gen()`，每条连接在 Starlette 线程池里占一个名额
   （默认 40），多开几个标签页、加上转录/状态请求，就开始排队。

### 1b 斜杠命令点击无反应、键盘却正常

`SlashPalette` 在 **mousedown** 里执行命令（为了抢在输入框失焦前）。React 18 对离散事件同步提交：
`/model`、`/permissions` 这类命令在同一个 mousedown 还在向 document 冒泡时就挂载了菜单，菜单的
`useEffect` 注册了 document 级"mousedown 落在外部就关闭"的监听；此时面板按钮已从 DOM 卸载，
`contains()` 判为"外部"，菜单在打开的同一刻被关掉。键盘 Enter 没有 mousedown，所以一直正常；
打开便签卡/对话框的命令（只监听 keydown 关闭）也不受影响，与"有的命令点得动"的现象一致。

### 2 工具卡永远"正在运行"

以真实会话 test4-0909 的转录（eid 2139–2156）复现：同一回合内两条 shell 命令并行，`command_output` /
`command_completed` 事件按"最新一张运行中的卡"配对，第二条命令的完成事件被记到第一条身上，第一条
永远留在运行中。工具事件同理（按工具名 FIFO，同名并行工具错配）。此外回合结束后前端没有任何
"收口"逻辑，任何漏掉终态的行就一直转圈。后端一侧：内核确实为每个 item 发 `item/completed`，
但 CrystalPilot 的归一化事件丢掉了 `item_id`，前端无从正确配对。

### 附带查实的两个根因

- **首次打开项目要几分钟 / 内核报 `failed to initialize sqlite state runtime`。** 不是项目本身，而是
  内核把自己的每一行日志写进 `codex-home/logs_2.sqlite`：三周长到 **1.6 GB**（引擎运行时约
  15 MB/min），带着 90 MB+ 的写前日志，下一次 app-server 启动卡在 sqlite 上。轮转后打开项目 1.5 s。
- **同一路径并发打开项目**（两个标签页同时进）各起一个内核，第二个因共享的 sqlite 状态库冲突失败。

---

## 二、变更清单（按提交）

| 提交 | 任务 | 内容 |
|---|---|---|
| `637170a` | 1a/1b/2 | Channel 心跳/关闭语义、异步 SSE、hello 带 oldest；`useThreadChannel` 重写（CLOSED/channel_closed/断档/45 s 看门狗/切回前台核对）、连接状态横幅；斜杠命令统一在 click 执行 + `outsideClick.ts`；所有 item 级事件带 `item_id`，按 id 配对；回合结束残留行 →「未收到结果」/「已中断」，原始事件可展开；`pool.open` 按路径加锁；本地便签在重建时保留；reducer 单测（真实夹具）+ Playwright `slash-commands`/`channel-selfheal` |
| `2bb3252` | 6 | `crystalpilot/refine/storage.py`：hkl 硬链接到反射数据版本、中间 CIF 剥离/交付恢复、预演式清理、占用统计；`run_shelxl`/WGHT/`run_shelxt` 改走 `_stage_job_hkl`；`write_outputs`/checkCIF 恢复；`/api/projects/usage`、`/api/projects/cleanup`；项目主页「项目占用」卡；重启脚本轮转 `logs_2.sqlite`；`tests/test_storage.py` |
| `505eef6` | 5 | `/api/projects/status` 按五处 mtime 缓存 |
| `718f91f` | 3 | `git merge --no-edit origin/Logo`（`design/CrystalPilot-logo-v1/`，8.3 MB 素材包保留） |
| `454e492` | 3 | `ui/public/brand/` 四个 SVG、`Brand.tsx`、左栏/欢迎页/项目主页、随主题 favicon、README Logo、Playwright `brand` |
| （本批最后两个提交） | 6 补 / 7 | 占用统计按类别只计一次硬链接；自动模式黑名单补 `secrets/` 与"改动源码目录"；优化清单；文档；本报告 |

文档：`README.md`（Status、Logo）、`docs/USER-GUIDE-2026-09-06.md`（§2.2 连接状态与「未收到结果」、
新 §2.4 项目占用与清理、§6 排障两条）、`ARCHITECTURE.md`（2026-09-16 addendum）、
`docs/INSTALL-LINUX.md`（日志库轮转）。

---

## 三、性能：先测再改

测量对象：本机 8010 服务，30 个近期项目，test3-2 副本（转录 2.4 MB）。

| 路径 | 之前 | 之后 | 做了什么 |
|---|---|---|---|
| `GET /api/projects/status`（左栏轮询） | 热 2.1 s，冷 36.8 s | 22–25 ms | 按 `.crystalpilot-workbench.json`/`state.json`/`nodes/`/`checkcif/`/`CrystalPilot Results/` 的 mtime 缓存每项目结果 |
| `POST /api/projects/open`（首次） | 数分钟（6.5–9 min 两次） | 1.5–1.8 s | 根因是 1.6 GB 的 `codex-home/logs_2.sqlite`，重启脚本轮转 |
| `GET /api/wb/threads/*/transcript`（2.4 MB） | 60 ms | 未改 | 够快 |
| `GET /api/wb/threads?project=` | 4 ms | 未改 | |
| `GET /api/folders` | 4 ms | 未改 | |
| `GET /api/models` | 冷 1.26 s / 热 10–33 ms | 未改 | 冷启动要问网关模型列表；建议后台预热（backlog） |
| `GET /api/projects/usage`（新） | — | 172 ms | 一次 scandir 遍历 + 大文件补 stat |
| 事件流 | 23% 事件是无用的 `item_unhandled` | 不再下发 | userMessage/agentMessage/reasoning 的 started/updated |
| SSE 连接 | 每连接占一个线程池名额 | 0 | 异步生成器 |
| 重启脚本 | 调用方等 85 s | 服务实际 ~4 s 就绪 | 未改脚本；85 s 是调用约定，可缩到健康检查通过即返回 |
| 前端主包 | 877 KB（gzip 283 KB）+ 3Dmol 574 KB | 未改 | 方向见 backlog（按路由懒加载） |

排序后的优化清单与"只做高收益低风险"的取舍在 `docs/OPTIMIZATION-BACKLOG-2026-09-16.md` 第二节。
所有改动不触碰任何科学计算路径；SHELXL/SHELXT 输入通过硬链接提供，字节相同。

---

## 四、存储治理

### 每一份副本是什么

| 位置 | 内容 | 处置 |
|---|---|---|
| `crystal.hkl`（项目根） | 用户输入 | 不动 |
| `.crystalpilot/refine/data/dNNNNNN/observations.hkl` + `sources/*.hkl` | 不可变的反射数据版本（正本）与其来源副本 | 正本；版本目录内部逐字节相同的副本改硬链接 |
| `.crystalpilot/refine/shelxl/job_*/job.hkl`、`shelxt/job_*/job.hkl` | 每个作业一份输入 | 改为指向版本正本的硬链接（新作业直接链接） |
| `shelxl/job_*/job.cif` 里的 `_shelx_hkl_file` 块 | SHELXL `ACTA` 内嵌的整份 hkl（`ACTA NOHKL` 被 2019/3 忽略） | 与 job.hkl 相同时换成一行引用标记，交付时按原字节恢复 |
| `shelxl/job_*/job.fab` | 掩膜系数，逐作业复制 | 逐字节相同的改硬链接 |
| `shelxl/job_*/job.fcf` | 结构因子表 | 被节点/交付引用或最近 3 个的保留；其余删除（`.ins/.res/.lst` 永远保留） |
| `checkcif/job_*/model.{ckf,ps,fcf,cif,hkl,fab,lst,lis}` | PLATON 中间产物 | `checkcif.json` 存在即删；`.chk/.vrf/checkcif.json` 保留 |
| `.staging/<txn>/` | 输入事务暂存 | 完成 >1 h 且大文件均已在版本目录 → 删除 |
| `CrystalPilot Results/**` | 交付件（含完整 CIF + hkl + fcf + fab） | 不动 |

### 前后（test3-2 副本，实际占盘）

| 类别 | 之前 | 之后 |
|---|---|---|
| SHELXL 作业目录 | 423.1 MB | 41.3 MB |
| 交付件 `CrystalPilot Results` | 80.4 MB | 80.4 MB（不动） |
| 暂存 `.staging` | 48.3 MB | 0 |
| 反射数据版本 `data/` | 48.3 MB（3 个版本 × 正本 + 来源副本，全部逐字节相同） | 6.1 MB |
| checkCIF | 41.6 MB | 0.7 MB |
| 用户数据 | 27.9 MB | 27.9 MB（不动） |
| SHELXT | 24.2 MB | 0.1 MB |
| 缓存（views/analysis） | 10.4 MB | 10.4 MB（可选清理，默认不动） |
| 节点库 | 6.3 MB | 6.3 MB（不动） |
| **合计（磁盘实际）** | **713 MB** | **175.7 MB**（其中系统生成 67.4 MB） |

目标"<100 MB"未达到，原因是交付件 80.4 MB + 用户数据 27.9 MB 已超过 100 MB，二者按约定不动；
系统生成部分从约 600 MB 降到 67 MB。正确性证明：22 份剥离的 `job.cif` 用 `restore_embedded_hkl`
恢复后与剥离前**逐字节相同**；50 + 7 份硬链接与被替换文件逐字节相同；回溯/对比/重算所需的
`.res/.ins/.lst`、节点库、反射版本一律未动。

### 保留规则（已写进用户手册 §2.4）

被节点树或交付（REPORT/MANIFEST/`metrics_source.job`）引用的作业完整保留；未引用作业保留
`.ins/.res/.lst`，只回收 `.fcf`；反射数据只存一份，作业目录用硬链接引用；中间 CIF 不含反射块，
交付件永远完整（`write_outputs` 与 checkCIF 暂存前恢复）；`nodes/`、`data/`、用户文件、
`CrystalPilot Results/` 永不修改；回合运行中拒绝清理（409）。

### codex-home / workdir

| 位置 | 大小 | 处置 |
|---|---|---|
| `codex-home/logs_2.sqlite` | 1621 MB（+ WAL） | 已轮转；重启脚本在 >256 MB 且无本仓库 codex 进程时删除 |
| `codex-home/sessions/` | 1012 MB | 转录来源，未动；归档语义见 backlog |
| `codex-home/thread_history_1.sqlite` | 72 MB | 未动 |
| `workdir/`（仓库内，gitignore） | **21.2 GB**：`dials/` 4.7 GB、`pytest-tmp/` 2.9 GB、`superflip_jobs/` 2.8 GB、`cap_zn/` 2.2 GB、`campaigns/` 1.7 GB、`cap_tune1/` 1.6 GB … | 全是历次实验/探针/求解作业的产物，本批**未删**；建议按第六节清单让用户逐目录点头（`pytest-tmp/` 与 `superflip_jobs/` 最可能可以直接删） |
| `H:\cp-pytest-tmp\` | 见第六节 | 回归副本 + basetemp，删前需用户确认 |

---

## 五、已验证事项（命令与结果）

- `cd ui && npx vitest run` - 574 passed（56 个文件；本批新增 pairing / lifecycle / notes 三组 reducer 单测）
- `cd ui && npx tsc --noEmit -p .`，通过
- `cd ui && npm run build`，通过（`index` 877 KB，3Dmol 574 KB）
- `.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider --basetemp=H:/cp-pytest-tmp/full-0916`
  ，**2846 passed / 31 skipped / 5 failed**（30 min 25 s；基线 2740 passed / 31 skipped，测试数增加来自 09-09
  合入的 Linux 分支）。5 个失败逐个核对：
  - 4 个在本批之前的提交 `ff1640b` 上（临时 worktree 复跑）**同样为红**：`test_peak_persistence::…keeps_the_provenance`
    （返回值多出 `map_provenance: None` 键）、`test_solver_state_budget` 两例、`test_ui_tool_sets::test_ui_mutating_set_mirrors_registry`。
    其中 `test_ui_tool_sets` 在本批修好（UI 的 `CRYSTAL_MUTATING` 补上 `set_adp`/`set_afix`/`set_site_occupancy`，
    与工具注册表一致）；`test_peak_persistence` 未修，留在 backlog。
  - `TestChargeFlipping::test_on_a_converged_solve` 与 `test_solver_state_budget` 的另两例在**单独重跑时通过**
    （3/3、10/10），失败信息是电荷翻转 worker 子进程退出码 1 与 `worker.log` 的 `WinError 32` 文件占用：
    Windows 上的时序/句柄抖动，与本批改动无关（本批未触碰 `crystalpilot/solve`），列入 backlog。
- 定向：`tests/test_storage.py` 17 passed；`tests/test_server_routes.py` 31 passed；
  `tests/test_approval_policy.py` 9 passed；`tests/test_item_lifecycle_events.py` 通过
- Playwright（从 `ui/`，`CP_E2E_PROJECT=H:/cp-pytest-tmp/handover-real/test3-2`
  `CP_SOL_THREAD=01a0800b-76d3-7451-b47f-8b4db4507a32`）：
  `health` `slash-commands`（28 例）`channel-selfheal`（5 例）`reconnect` `feed-reconnect` → 37 passed
  （第一轮 `health` 因源码新于构建而红、`reconnect` 在与 `du` 大 IO 同跑时分页 30 s 超时；重建并空闲
  后 `health`/`reconnect`/`brand` 8 passed）；截图 `workdir/ui-evidence/r0/brand-*.png`、
  `channel-offline-banner.png`
- 存储：副本上 `apply_cleanup` 两轮（109 + 7 项，0 跳过）；剥离 CIF 逐字节恢复 22/22；硬链接 57/57 相同
- SHELXL 真跑（`-t4`）确认内嵌规则与 `ACTA NOHKL` 被忽略
- 重启脚本：`restart_server.ps1` 完成日志库轮转（"rotated codex log database (1621 MB)"），服务 ~4 s 就绪，
  `/api/health` `ui_build.stale=false`
- 新机器 clone：`git clone H:/CrystalPilot H:/cp-pytest-tmp/fresh-clone` 成功，`design/` 在、
  `vendor/` 只有 `VENDOR-STATUS.md`、无 `secrets/`、无 `.venv`、无 `ui/dist`；按 README 走
  `python -m venv .venv` + `pip install -e .[server,workbench,refine]`（Python 3.12.4）成功：cctbx-base 2025.11、
  rdkit 2026.3.6、gemmi 0.7.5、mcp 1.30.0、openai-codex 0.147.0（自带 pip 内核 0.147.0）；
  `import crystalpilot, crystalpilot.workbench.service, server.app` 正常；用 clone 自己的环境跑
  `tests/test_storage.py` `tests/test_approval_policy.py` `tests/test_item_lifecycle_events.py` `tests/test_server_routes.py`
  → 67 passed / 2 skipped / 1 failed（`TestGzip::test_large_json_gzipped`：它请求的旧接口 `/api/projects/list`
  在没有本机运行记录的干净 clone 上返回 404，是依赖本机数据的测试，不是安装问题；列入 backlog）。
  发现并已修的文档缺口：README 的 pip 命令缺 `dev` extra，clone 里没有 pytest；已改为 `.[server,workbench,refine,dev]`。
- 推送：`git push origin main:main`（只推 main；不推其他分支，不触碰 `origin/codex/argus-crystalpilot-plugin-20260910`）。
  推送前 `git status -sb` 为 `main...origin/main [ahead 18]`；**已推送**：`8e945f1..a03835c  main -> main`，
  `git fetch` 后 `main...origin/main` 同步；远端仍是 4 个分支，`origin/codex/argus-crystalpilot-plugin-20260910`
  未被触碰。本行由紧随其后的收尾提交补记并再推一次 main。

## 六、未验证事项及原因

- **长会话（>4 h）的前端内存/帧率与后端 RSS**：未测，需要一次真实长回合；方案在 backlog 建议 9。
- **Linux 上 `server_linux.py` 的日志库轮转**：与 Windows 同一逻辑，本机无 Linux 环境，未运行。
- **`write_outputs` 在剥离后作业上的端到端交付**：做了函数级逐字节恢复验证，没有跑完整的模型回合。
- **子进程 CPU/内存上限的运行时核对**：`procutil.py` 覆盖 SHELXL/PLATON/DIALS，本轮只读代码，
  未在任务运行中抓取 affinity/优先级。
- **`H:\cp-pytest-tmp\` 的完整体积**：`workdir/` 已测（21.2 GB，第四节）；`H:\cp-pytest-tmp\` 的 `du` 在写完报告时
  仍未跑完（回归副本 + 各次 basetemp + 干净 clone 的 .venv，估计数 GB 到十几 GB），没有拿到准确数字。
- **`reconnect` 规格的一次分页超时**：判定为 IO 争用（空闲重跑通过两次），没有做进一步的注入复现。
- **新机器完整安装的后半段**：pip 部分已在干净 clone 上验证（见第五节）；`npm install && npm run build`、
  `setup_vendor_shelx.py`（需要授权的 SHELX/PLATON 安装源）、`update_codex_kernel.ps1`（需要 Node/npm 与网络）
  和真正启动服务**未在 clone 上跑**: SHELX 源与 npm 内核下载不在本轮资源预算内，且启动会占 8010。

## 七、新机器部署清单

仓库里**没有**、必须单独准备的东西（`git clone` 之后）：

1. **Python 3.12 + 虚拟环境**：`python -m venv .venv`；`.venv/Scripts/pip install -e .[server,workbench,refine]`
   （Linux：`docs/INSTALL-LINUX.md`，`requirements-linux.lock`）。
2. **SHELXL / SHELXT / PLATON**（授权二进制，`vendor/` 被 gitignore）：
   `python -X utf8 scripts/setup_vendor_shelx.py --source <已安装目录>`。
3. **codex 内核**（`vendor/codex`，gitignore）：需要 Node.js + npm；
   `powershell -File scripts/update_codex_kernel.ps1`（Linux 见安装文档）。没有它时退回 pip SDK。
4. **其余外接软件**（可选，`vendor/VENDOR-STATUS.md`）：Olex2、gavrog、jana2020、superflip、CrysAlisPro。
5. **密钥**：`secrets/`（OpenRouter 等）与 `testAPI.txt`（网关），永不入库，手工放置；
   自动模式黑名单现在拦截任何触碰 `secrets/` 的 shell 命令。
6. **前端**：Node.js；`cd ui && npm install && npm run build`（`ui/dist` 不入库）。
7. **codex-home**：`config.toml` 与 `model_catalog.custom.json` 已入库（其中的 162 条 trust 条目是
   本机路径，新机器上无害）；`sessions/`、`logs_2.sqlite` 等由内核首次运行生成。
8. **启动**：Windows `scripts/restart_server.ps1`（唯一正规方式，selector 事件循环 + 健康轮询）；
   Linux `scripts/server_linux.py start`。健康：`GET /api/health`（`ui_build.stale` 必须为 false）、
   `GET /api/kernel`。
9. **项目放仓库外**（如 `H:\CrystalPilot-campaigns\`）：自动模式下对仓库内路径的删/移/写会转为人工审批。
