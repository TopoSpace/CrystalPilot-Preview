# 全景审视与优化清单（2026-09-16）

审视范围：正确性、用户体验、科学工作流、代码健康、运维、安全。证据来自本轮的真实会话回放
（test3-2 / test4-0909 副本）、服务日志、代码阅读与实测。配套报告：
`docs/REVIEW-2026-09-16-stability-logo-sync.md`。

分三档：**已实施**（本轮已改并验证）、**建议实施**（收益明确、需要单独排期或用户决定）、
**不建议**（评估过，收益不抵风险或与既定原则冲突）。

## 一、已实施

| # | 领域 | 问题（根因） | 做法 | 验证 |
|---|---|---|---|---|
| 1 | 正确性/UX | 页面停住不更新：EventSource 收非 2xx 永不重试；闲置会话回收后旧通道静默失效；无心跳 | SSE 心跳 `ping` + `channel_closed`；hello 带 `oldest`；前端看门狗/断档重拉/切回前台核对；连接状态横幅 | vitest；Playwright channel-selfheal 5 例 |
| 2 | UX | 斜杠命令点击无反应：mousedown 内执行 + React 18 同步提交 + 点外部关闭 | 命令统一在 click 执行；`outsideClick.ts` 忽略已脱离文档的目标 | Playwright 14 命令 × 点击/键盘 |
| 3 | 正确性 | 工具卡永远"正在运行"：完成事件按"最新一张卡"配对 | 全部 item 级事件带 `item_id`；回合结束残留行标"未收到结果"；原始事件可查 | reducer 单测（真实夹具）+ `tests/test_item_lifecycle_events.py` |
| 4 | 正确性 | 同路径并发打开项目起两个内核、第二个失败 | `WorkbenchPool.open` 按路径加锁 | 代码路径 + 复现日志 |
| 5 | 运维/性能 | 首次打开项目要几分钟；"failed to initialize sqlite state runtime" | 根因是 `codex-home/logs_2.sqlite` 1.6 GB；重启脚本 >256 MB 时轮转 | 重启后打开项目 1.5 s |
| 6 | 性能 | `/api/projects/status` 热 2.1 s / 冷 36.8 s | 按五处 mtime 缓存每项目结果 | 25 ms；`tests/test_server_routes.py` |
| 7 | 性能 | 事件流 23% 是 `item_unhandled`（userMessage/agentMessage/reasoning 的 started/updated） | 不再下发 | 真实转录统计 |
| 8 | 存储 | 反射数据每作业一份、CIF 再内嵌一份、PLATON 中间产物、暂存目录不清 | `storage.py`：硬链接 + 可恢复剥离 + 预演式清理 + 项目占用卡 | 713 → 212 MB；22 份 CIF 逐字节恢复 |
| 9 | 安全 | 自动模式的 shell 放行黑名单只点名 `testAPI.txt`，`secrets/` 目录与源码目录 `H:\CrystalPilot` 都不受保护 | 黑名单加 `secrets[\\/]`（读也拦）与"改动源码目录"（删/移/写/`git checkout|reset|…` + 本仓库根路径；读不拦；`H:\CrystalPilot-campaigns` 等兄弟目录不受影响） | `tests/test_approval_policy.py` 新增两组 |
| 10 | UX/品牌 | 无 Logo | 合入 origin/Logo，左栏标志、欢迎页/项目主页应用图标、随主题 favicon | Playwright brand 4 例 + 截图 |
| 11 | 健壮性 | 斜杠便签在首个转录到达/重连重拉时丢失 | reset 重建时保留客户端本地便签 | reducer 单测 |

## 二、建议实施

按收益/风险排序，附估算。

1. **转录里的图片链接改为项目相对路径**（UX，中）。现在 agent 消息里的 `views/*.png` 链接是绝对路径；
   项目目录一旦移动/复制（回归副本上就是这样），缩略图 404。`mdLink.tsx` 已能解析相对 href，
   缺的是生成侧（工具返回值）用相对路径。半天。
2. **`codex-home/sessions` 轮转**（运维，中）。1.0 GB 的 rollout jsonl 是转录来源，不能盲删；建议
   "项目归档"动作把对应线程的 rollout 压缩移到项目 `.crystalpilot/archive/`，并在左栏"隐藏"时提示。
   需要用户对归档语义点头。1–2 天。
3. **`H:\cp-pytest-tmp` 与 `workdir/` 里的旧探针**（运维，低风险）。回归副本、basetemp、`_probe/*`、
   `ui-cif-browser-*` 合计约 0.85 GB+；属可删，但里面有用户回归副本，删前请用户确认清单。
4. **前端主包 877 KB（gzip 283 KB）**（性能，低）。3Dmol 已单独分块（574 KB）；下一步把设置面板、
   分析页签、Markdown 渲染按路由懒加载，预计首屏 -30%。一天。测量优先：先加 `vite-bundle-visualizer`。
5. **`/api/models` 冷启动 1.26 s**（性能，低）。首次请求要问网关模型列表；可在服务启动后台预热。
   两小时。
6. **工具卡"未收到结果"的服务器侧兜底**（正确性，中）。前端已能收口；后端可在 `turn/completed` 时
   把仍 in_progress 的 item 主动补一条 `*_completed(status=unknown)` 写进转录，这样离线读转录的
   脚本也不再误判。半天；需要确认 codex 不会在 turn/completed 之后再补发 item/completed。
7. **`ui/src/legacy/`**（代码健康，低）。`App.tsx` 仍挂 `/legacy` 路由（Home/RunView/RecentRuns）。
   README 说"legacy pages remain at /legacy"，若无人再用，可整块删除并去掉路由；先在设置面板加
   一条使用统计再决定。
8. **自动模式黑名单的项目位置约束**（安全/UX，说明性）。新规则以本仓库根路径为界；若用户把项目
   建在 `H:\CrystalPilot\workdir\...` 之类仓库内路径，自动模式下的删/移/写命令会转为人工审批。
   文档已写明"项目放仓库外"；可在"打开项目"对话框里对仓库内路径给出提示。两小时。
9. **测量而非猜测的长会话内存**（性能，未测）。本轮未测 8 小时级长会话的前端内存与后端 RSS；
   建议在 `/api/ui/diagnostics` 加 `performance.memory` 采样（Edge/Chrome 可用）与服务端 `psutil`
   RSS，跑一次 usertest 长会话后再决定是否需要转录窗口化。
10. **子进程 CPU/内存上限的统一入口**（运维，中）。`procutil.py` 已给 SHELXL/PLATON/DIALS 用；
    `frames_dials.py` 与 `campaign_logs.py` 各自引用；建议统一从 `procutil.limited_popen` 走，
    并在 `/api/health` 里报告实际生效的 affinity/优先级。半天。

11. **电荷翻转 worker 在 Windows 上的抖动**（代码健康，中）。全量 pytest 里 `TestChargeFlipping::test_on_a_converged_solve`
    与 `test_solver_state_budget` 两例偶发失败（worker 退出码 1；`worker.log` 的 `WinError 32` 文件占用导致临时目录
    清理失败），单独重跑通过。方向：worker 退出前关闭日志句柄、父进程等待子进程真正退出后再 `rmtree`，
    并把 worker 的 traceback 完整写进 `summary.worker_error` 而不是被截断。半天。
12. **`test_peak_persistence::test_checkout_via_the_tool_keeps_the_provenance`**（正确性，低）。在 09-09 合入的 Linux
    分支之后就红：checkout 返回的峰表多了 `map_provenance: None`。要么补齐来源，要么更新期望；需要先确认
    `map_provenance` 的设计意图。两小时。

13. **依赖本机数据的测试**（代码健康，低）。`tests/test_server_routes.py::TestGzip::test_large_json_gzipped` 请求旧接口
    `/api/projects/list`，在没有运行记录的干净 clone 上 404；应改为对固定的大 JSON 路由（或注入的测试数据）断言。
    一小时。
14. **`workdir/` 21.2 GB**（运维，高收益、需要用户点头）。`dials/` 4.7 GB、`pytest-tmp/` 2.9 GB、`superflip_jobs/` 2.8 GB、
    `cap_zn/` 2.2 GB、`campaigns/` 1.7 GB、`cap_tune1/` 1.6 GB……全是历次实验/探针/求解作业产物（gitignore，
    不影响仓库）。建议先把 `pytest-tmp/`（basetemp 已改到仓库外）与 `superflip_jobs/` 列给用户确认删除，
    其余按目录逐个决定；系统不自动动它们。

## 三、不建议

1. **对 `CrystalPilot Results/` 交付件做硬链接去重**。副本上 4 份 final.cif（8.8 MB × 3 + 6.1 MB）
   多半逐字节相同，去重可再省 ~25 MB；但交付件是用户要拿走、可能就地编辑的文件，硬链接会让
   "改一份两份都变"。不做；项目占用卡如实显示它们的体积。
2. **删除或截断 `codex-home/sessions` 里的旧 rollout**。它们是转录的唯一来源（`/api/wb/threads/*/transcript`
   从这里读），删了左栏历史就空了。只在"归档"语义确定后做（见建议 2）。
3. **把"未收到结果"改成灰色/隐藏**。这是用户明确要求的诚实状态：回合结束却没有结果本身就是
   值得注意的事，不能用弱化视觉来掩盖。
4. **缩短 `APPROVAL_TIMEOUT_S=900` 或 `IDLE_SHUTDOWN_S=1800`**。缩短并不能修"页面卡住"（根因是
   断连不自愈，已修），反而会让长时间思考的审批更早超时。
5. **删除 vendor 下任何外接软件 / 归档 D: 盘 worktree / 改动原网关配置**。与用户 2026-09-10 的决定
   和本轮约束相反，不做。
6. **用文件哈希做项目内容审计**。用户明确不要；存储模块只用尺寸 + 逐字节比较。
7. **自动删除 `H:\cp-pytest-tmp`**。里面有回归副本，属用户资产；只列出、不动。

## 四、本轮未验证、需要后续确认的事项

- 长会话（>4 h）的前端内存与帧率：未测（见建议 9）。
- Linux 上 `server_linux.py` 的日志库轮转分支：代码路径与 Windows 相同，但本机没有 Linux 环境，
  未实际运行。
- `write_outputs` 在一个真实的剥离后作业上端到端跑一遍交付（本轮做了函数级逐字节恢复验证，
  没有跑完整的 `write_outputs`，因为那需要一次真实模型回合）。
