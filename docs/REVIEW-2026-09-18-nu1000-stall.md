# 2026-09-18 排查报告：NU-1000 两次"停在第 2 个节点"

范围：`H:\CrystalPilot-campaigns\usertest\test-NU1000` 与 `test-NU1000-2` 两个真实用户会话（只读取证），
仓库 `H:\CrystalPilot`（内核 npm codex 0.155.0）。本报告只写查实的事实；未验证的项目明确标"未验证"。

---

## 一、现象

用户用正确的 NU-1000 数据（034A1，同步辐射 λ = 0.68883 Å，a = 39.19 Å，c = 16.61 Å，6/mmm）
先后开了两个项目，两次都"一直停留在：start.ins 里还留着 4 个零坐标占位原子，context.json 没有任何先验。
两个项目都停在第 2 个节点"。

## 二、证据链（全部来自转录、内核回放与作业目录，未改动任何用户文件）

| 证据 | test-NU1000 | test-NU1000-2 |
|---|---|---|
| 用户消息 | 16:31:49 | 16:43:26 |
| `run_shelxt(detach=true)` 启动 | 16:34:38（pid 见 `_jobs.json`） | 16:46:11（`Zr18 C264 O96`，`timeout_s 600`） |
| 回合结束方式 | 16:38:13 `turn_completed status=interrupted`（375 s） | 16:55:51 `interrupted`（741 s） |
| 内核回放 | `turn_aborted reason:"interrupted"` + "The user interrupted the previous turn on purpose" | 同 |
| 访问日志 | `POST /api/threads/interrupt`（`workdir/uvicorn_r13.log` 677 / 955 行） | 同 |
| SHELXT 实际结束 | 16:50:46，`has_solution: true`，总 964.6 s | 17:00:34，`has_solution: true`，总 860.6 s |
| SHELXT 各阶段（job.lxt） | 相位求解 ~28 s；空间群搜索 ~807 s | 相位求解 34.8 s；**空间群搜索 775.0 s**；元素指认 50.1 s |
| 搜索范围 | `-a set to extend space group search because atom heavier than Sc expected`，6/mmm 全部 18 个群 | 同（4 个中心对称 + 14 个非中心对称） |
| 结果 | 未被采用（回合已停，没有下一回合执行 `from_job`） | 同；候选 P6/mmm R1 0.327、P6mm、P-6m2、P622、P-62m |

界面里能看见的只有：几张 `run_shelxt(job_status=…)` 轮询卡、几条 `Start-Sleep -Seconds 30`、
Agent 的"等待求解时…"说明；节点树停在 n0001（分辨率截断节点）；状态轨在 Agent 睡眠时显示的是
"等待 30 秒"，回合被停后显示"上次回合已中断"。**没有任何一处说明有一个 SHELXT 正在后台跑、跑到了哪一步、
大概还要多久。**

## 三、根因

1. **两次都是用户按了「停止」，不是解析失败。** 内核回放与访问日志都证明回合是被用户主动中断的；
   SHELXT 在两个项目里都在中断之后 10–15 分钟解出了结构。
2. **慢的原因是 SHELXT 的空间群搜索，而且这一阶段 SHELXT 一个字都不输出。** 声明 Zr（重于 Sc）后
   SHELXT 自动加 `-a`，逐个评估 Laue 类 6/mmm 里全部 18 个空间群；这个 39 Å 六方大胞上历史耗时
   240–570 s，今天 775–807 s（当时我的仓库级 grep 在同机以 BelowNormal 优先级跑着，很可能拖慢了它）。
   相位求解本身只要 28–35 s。
3. **后台作业在界面上完全不可见。** 看门狗与作业登记表都在 MCP 工具进程里（`tools_shelxl._DETACHED`、
   `.crystalpilot/refine/shelxt/_jobs.json`、每个作业的 `progress.json`），Web 服务与前端对它一无所知：
   没有运行中的卡、没有进度、节点树静止、状态轨说"空闲/已中断"。
4. **工具自己的进度也误报。** `job_status` 的 `per_try_s` 用"总用时 ÷ 尝试数"算，相位结束后墙钟继续走，
   12 次 3 s 的尝试被报成 72–80 s/次；对搜索阶段没有任何用时、参考或解释。
5. 占位原子与空的 context.json **不是原因**（Agent 已按提示自己处理；我之前一句"两处会拖累解析"说错了）。

## 四、修正（根因级，非文案）

### 工具层 `crystalpilot/refine/tools_shelxl.py`
- `_phasing_estimate`：相位结束后按 SHELXT 记录的 `Structure solution` 时间算每次尝试的用时（35 s / 12 = 2.9 s），
  不再用墙钟；相位未结束时行为不变。
- 新增搜索阶段事实：`auto_a` / `exhaustive_search`（-a 全类搜索）、`search_elapsed_s`、
  `search_reference`（**本项目**先前同 Laue 类、同搜索范围作业的 `Space group determination` 用时，
  不是任何晶体常数）、`search_note`（SHELXT 此阶段不输出；重原子触发 -a；`space_group=` 可跳过）。
  写入 `job_status` 结果、`progress.json` 与心跳行。
- 搜索宽限（`search_grace_s`）用完时不再直接杀：若 SHELXT 进程仍在消耗 CPU（psutil 采样 ≥ 0.2 核）
  就按片延长，总延长上限 2 × `search_grace_s`；进程空闲（挂死）仍照旧杀掉。被杀的诊断里如实写出实际宽限。
  这只改变"健康的搜索是否会被预算误杀"，不改变任何科学结果（杀掉的搜索本来就不可恢复）。
- `run_shelxt(from_job=…)` 采用后在登记表写 `adopted_at`；`detach` 返回说明与参数说明告知模型：
  工作台会持续显示该作业、可结束回合而不必睡眠轮询；重原子下搜索长且静默；`space_group=` 可跳过。

### 服务层 `crystalpilot/workbench/background_jobs.py`（新）+ `service.py` + `routes.py`
- 每个打开的项目一个监视线程，只读 `_jobs.json` / `progress.json` / `job.lxt` 与 pid 存活，
  产出 `background_job` 事件：`started / stage / finished / killed / failed / died / adopted`
  写进发起回合所在线程的转录（有 eid），`heartbeat`（运行中每 15 s）与 `snapshot` 只走实时通道。
- 回合结束后监视不停；服务重启或项目重开时，已完成但未采用的解会在打开时出现一次；
  `GET /api/threads/transcript` 的最新一页末尾附带当前作业快照（无 eid），刷新页面不丢。
- 不写项目下任何文件。

### 前端
- 新事件类型 `BackgroundJobEvent`；reducer 维护 `backgroundJobs`，每个作业**一条系统行**原地更新，
  始终 `done=true`，回合边界不会把它标成"已中断"；`run_shelxt(from_job=…)` 成功后该行改为"结果已采用 → 节点 nXXXX"。
- 系统行文案（`ui/src/lib/backgroundJobs.ts`）：
  `SHELXT 后台求解 · 空间群搜索 · 已 5 分 12 秒（声明了重原子，SHELXT 逐个评估 Laue 类内全部空间群，此阶段不输出任何内容；本项目先前同类搜索约 12 分 55 秒）`；
  完成后：`SHELXT 后台求解 已完成（用时 14 分 23 秒，最佳 CFOM 0.737，6/mmm 评估了 18 个空间群） · 尚未采用，新回合里让 Agent 执行 run_shelxt(from_job='job_…') 即可采用`。
- 状态轨：回合运行中，当前动作行带上后台作业（`等待 30 秒 · SHELXT 后台求解 · …`）；回合已结束但作业仍在跑时
  显示新状态 `background`（转圈 + 用时计数 + "回合已结束，后台仍在求解，完成后会在对话里提示"），
  不再显示"空闲/上次回合已中断"；有已完成未采用的解时在"空闲/已中断"后追加"SHELXT 求解已完成，待采用"。

## 五、验证

| 项 | 结果 |
|---|---|
| `tests/test_shelxt_progress.py` + `test_shelxt_staged.py` + `test_pa2_tool_fixes.py` | 67 passed |
| `tests/test_background_jobs.py`（新：估算、参考、CPU 宽限、假 SHELXT 被杀/被延长、监视器状态机） | 22 passed |
| 前端 `tsc --noEmit` | 通过 |
| `threadReducer.backgroundJob.test.ts`（新 7 项）+ statusRail / lifecycle / pairing / startup / grouping | 95 passed |
| 前端全量 vitest | 57 个文件 581 passed |
| `tests/test_transcript_paging.py` + `test_server_routes.py`（转录引导附带快照） | 48 passed |
| `npm run build` → `scripts/restart_server.ps1` → `/api/health` | `ui_build.stale=false`，两次重启均 2 s 内起来 |
| 真实项目核对（只读 API）：打开 test-NU1000-2 / test-NU1000 后 `GET /api/threads/transcript` 最新页 | 各附带 1 条 `background_job` 快照：`job_20260918_164612`（finished，has_solution，搜索 775 s，18 群，CFOM 0.737）/ `job_20260918_163438`（finished，has_solution，搜索 807 s，CFOM 0.744），均 `adopted_at: null` |
| 实时通道核对：副本项目上植入合成"运行中"作业后监听 SSE | 0.0 s 收到 `started`，15.1 s 收到 `heartbeat`（阶段 space-group search，用时递增） |
| Playwright `ui/e2e/background-job.pw.ts`（新；副本项目 test3-2，合成作业，跑完自清理） | 1 passed（10.3 s）；截图 `workdir/ui-evidence/bgjob-0918/background-job-running.png`（状态轨「SHELXT 后台求解 · 空间群搜索 · 已 5 秒（声明了重原子…）」+ 对话末尾系统行）、`background-job-finished.png`（系统行「已完成（用时 1 分 52 秒，最佳 CFOM 0.731，6/mmm 评估了 18 个空间群） · 尚未采用 —— …run_shelxt(from_job='job_e2e_bg')…」，状态轨「空闲 · … · SHELXT 求解已完成，待采用」；刷新后仍是同一条行） |
| e2e 副作用 | 注册表 30 → 30，无 `ui-cif-browser-*` 残留，`config.toml` 干净；副本项目登记表按备份恢复、合成作业目录已删 |

已知的小差异：系统行里的"已 N 秒"随每 15 s 一次的心跳刷新，状态轨的计时每秒走（用服务端给的开始时刻推算），两处可能相差十几秒；求解结束后两处一致。

首次核对时发现并已修的一处：监视器原本只在线程里做第一次轮询，`/api/projects/open` 返回后立刻拉转录会漏掉快照（实时通道能收到、引导页没有）；现在 `start()` 先同步轮询一次再起线程，重启后复核两个真实项目均带快照。

## 六、对用户的说明

- 两个项目里 SHELXT **都已经解出来了**，解在各自的 `.crystalpilot/refine/shelxt/job_…/job_a.res`。
  在对应项目开一个新回合，让 Agent 执行 `run_shelxt(from_job='<作业名>')` 即可采用，不必重跑 15 分钟：
  - test-NU1000：`job_20260918_163438`
  - test-NU1000-2：`job_20260918_164612`
- 以后再跑 NU-1000 这类含 Zr 的六方大胞：相位求解约半分钟，空间群搜索 10–15 分钟且程序不输出，
  现在界面会明确显示这一阶段与本项目先前的参考用时；若空间群已经确定，让 Agent 传 `space_group=` 可以直接跳过搜索。
- 占位原子与 context.json 与这次的停顿无关。

## 七、未验证 / 未做

- "今天比历史慢一倍"归因于同机负载（我的 grep）属推断，未做对照实验。
- 服务重启后仍在跑的 SHELXT：监视器只能靠 pid 存活判断"仍在跑"，MCP 侧的看门狗要等 Agent 下次 `job_status` 才重挂；
  这一路径只有单元测试，未在真机上演练。
- 节点树在求解期间仍然静止（求解本来就不产生节点），未改。
