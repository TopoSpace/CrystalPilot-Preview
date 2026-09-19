# 第三轮 R0–R1 复盘（2026-09-05）

> 计划：`docs/PLAN-2026-09-05-round3.md` §3 R0、R1。tag：`r3-pre`（基线）→ `r3-r1-done`。
> 提交：`beece50`（R0）、`c443fff`（R1 前端）、`1315218`（R1 服务端+客户端）、`0c8794b`（并发冷启动修复）、本文档提交。

## 一、修好了什么

### R0 运维与基线

| 项 | 结果 |
|---|---|
| 服务器重启 | `scripts/restart_server.ps1` 成为唯一入口：按命令行 `uvicorn server.app:app --port 8010` 识别进程（venv 启动器在进程表里显示为 pyenv 基解释器，旧脚本按路径匹配永远认不出），只杀这棵树，`.venv` 隐藏启动，日志固定 `workdir/uvicorn_r13*.log`，PID 文件 `workdir/uvicorn_r13.pid`，健康轮询。**必须裸跑，不能把它的输出接管道**（接了管道 bash 会等子进程句柄）。 |
| 实机启动器 | `scripts/run_live.py --source … --name … --brief … --context …`：项目建在仓库外、只拷 `crystal.hkl`/`start.ins`、写设置、暖机回合、等 MCP 就绪、发简报、镜像 SSE 到 `events.jsonl`，启动即打印可打开的浏览器 URL。 |
| 推理档位 | 探针证实网关接受 gpt-6-astra 的 `max`/`ultra` 真实回合（`EFFORT-PROBE.md`）；`EFFORT_CHOICES` 六档，"最高档"判定 = xhigh 及以上，UI 显示 极高/最高/超高。 |
| 基线 | 全量 pytest 2300 passed / 25 skipped（29 个失败与报错全部来自 `--basetemp` 放在仓库内触发的"结构项目必须在仓库外"守卫，换到仓库外 66/66 通过）；vitest 267；`npm run build`；Playwright 16 passed / 4 skipped（缺结构文档夹具）。证据 `workdir/ui-evidence/r3-pre/`。 |

### R1 前端稳定性与可观测性（取证 F-1…F-8）

| 取证编号 | 修法 | 证据 |
|---|---|---|
| F-3 去重只看末 80 条 `(kind,ts)` | 服务端每条落盘事件盖 `eid` = transcript 行号（`core._log_event`），用户消息由 service 先落盘再推送、插话回显带同一 eid；前端按 eid 精确去重（512 条近期窗 + maxEid），无 eid 的旧事件退回旧窗 | vitest 回放取证的 83 行 + 2 条 SSE 重放：无 eid → 复现幽灵"运行中 branch"卡；有 eid → 零新增 |
| F-2 SSE 固定 `after=0`、通道重建后编号错位 | transcript 快照返回 `live_cursor` + `generation`；SSE 从 `live_cursor` 续传；每条连接先发 `channel_hello{generation}`，代际不同即重新拉取 | Playwright：真实线程的 hello 代际 = transcript 快照代际 |
| F-1 只取末 2000 行、无分页 | `GET /threads/transcript?before=&limit=` → `total/oldest_eid/has_more`；前端"加载更早的记录 · 还有 N 条"，从原始事件重建 | Playwright：10 224 行的实机演示线程，逐页加载后 5 条人类输入各出现一次，刷新后同样 |
| F-4 300 块显示窗把插话挤出 DOM | 被挤出的用户/插话气泡常驻在"更早的输入"区 | vitest + 截图 |
| F-5 插话当分段边界、折叠顺序倒置 | 插话不再切段；每段 quiet 行各自折叠、不跨 loud 行；顺序 = 事件顺序 | vitest（order/steer 用例） |
| F-6 完成事件的 1500 字符尾覆盖 16 000 字符流 | 保留更长的流式文本；完整输出落 `command_output/<item>.txt`，命令卡"查看完整输出" | vitest + 服务端测试 |
| F-7 秒当毫秒 | `spanMs()` 统一换算 | vitest（2904 s 不再显示 00:03） |
| F-8 无 ErrorBoundary、`previewOf(null)` 崩溃 | 四个区域各自 ErrorBoundary（可"重新加载此区域"/"复制诊断"）；`window.onerror`/`unhandledrejection` → `POST /api/ui/diagnostics` → `workdir/ui-diagnostics.jsonl`（带线程/游标/条数上下文） | vitest + Playwright（诊断端点） |
| 指标页 | `n_params<0` 不再画成"参数 −1"；`d_min` 标"数据标称"，SHEL 卡给"工作截断" | vitest（`shelWorkingCutoff`） |

服务端测试：`tests/test_transcript_paging.py`（17 例：分页、行号身份、损坏行不移位、命令输出端点与路径守卫、hello、诊断端点）。

### 实机暴露并修好的一个真 bug：并发冷启动

第一格 org_hsl（21:11）整场只剩 `crystalpilot_error`："project failed to open"。取证：Codex 在规格缓存冷（代码指纹变了）时**同一秒起了两个** crystalpilot MCP 进程（`mcp_server.jsonl` 两条 startup 都 `cache_hit:false`），二者同时走 `open()` → 导入起始模型 → 提交 n0000 → 写 `state.json`，而 `NodeStore._save_state` 用的是共用临时名 `state.json.tmp`，Windows 下第二个进程撞上 WinError 32（"状态文件被占用"，agent 的原话就是这个意思），从此整场只有错误工具；codex 不保留 MCP 子进程 stderr，异常原文丢失。

修法（`0c8794b`，通用、不针对测试晶体）：
- `nodes.atomic_write_json`：按进程唯一临时名 + `os.replace` 重试；`read_json_retry` 容忍另一进程正在换文件；state / peaks / node.json 都走它。
- `RefineProject._bootstrap_once`：`bootstrap.lock`（`O_EXCL`）保证只有一个进程导入起始模型，其余等待其提交后 `checkout` 续用；陈旧锁与中途消失的持有者都有处理。
- MCP `ProjectHandle`：打开失败不再把半开的项目当已打开；`tools/list` 重试三次、每次失败把异常与 traceback 写进 `.crystalpilot/mcp_server.jsonl`（`open_failed`），下次再出问题有据可查。
- 回归：`tests/test_concurrent_open.py`（6 个写者并发写同一状态文件、**三个真实进程同一时刻打开同一新项目**只产生一个 n0000、陈旧/消失/正在提交的锁持有者、句柄重试）。

## 二、验证了什么（真实数据）

**一格小分子 `org_hsl`（COD 2241460，N-(3-oxobutanoyl)-L-homoserine lactone，C8H11NO4，P2₁2₁2₁）**，输入为 ka1-org 战役的冷启动 `start.ins`（只有 TITL/CELL/ZERR，P1、无原子、无元素清单）+ 真实 HKL，简报为通用简报加一句"约 20–30 分钟内完成"。项目 `H:\CrystalPilot-campaigns\r3\r1-org-hsl-2`，线程 `01a071bd-…`，日志 `workdir/campaigns/r3-r1/`（`events.jsonl`、`state.json`、简报、评分）。

| 项 | 结果 |
|---|---|
| 墙钟 / 调用 | 16 min 38 s（997 825 ms）/ 53 次工具、1 条命令、2 次插话回合（含暖机） |
| 交付 | `final`，节点 n0013；R1 0.0263 / wR2 0.0688 / GooF 1.035；Flack −0.01(8)；无掩膜、无分裂无序、无 restraints；SHELXL 与 Olex2 复核一致 |
| 评分（`crystalpilot.benchmark.grade`，参考 = 发表 CIF） | **publication**：13/13 非氢原子匹配、rms 0.001 Å、元素错配 0；交付 RES 零轮重放 R1 0.0263（Δ 0.0）；模型移植到参考数据 R1 0.0263 vs 发表 0.0264；树内最佳 = 交付节点 |
| checkCIF | 7 A / 3 B / 4 C；7 个 A 全是实验元数据缺项（183/184/185/197/198/699 + 881），agent 逐条豁免并写明"须补原实验记录、不代填"，评分器同样归为 metadata incomplete 不计分 |
| 诚实性 | SUMMARY 明确"尚不能直接投稿"、温度/尺寸/吸收校正待补、绝对构型 s.u. 0.08 不作高精度表述 |

UI 侧：运行态截图（`live-org-hsl-2-running-01.png`：阶段轨在"验证"、状态药丸"思考中… 05:59"、右栏 n0007 R1 0.0263）、完成态两主题（`live-org-hsl-2-done-*.png`：交付摘要卡 final · 豁免 11）。刷新/重连用例跑在 10 224 行的实机演示线程上（`reconnect-*.png`）。

## 三、没做什么 / 观察到的问题（进 R2 及以后）

- 交付摘要卡把 `command_output/*.txt` 与 `transcript.jsonl` 也列成芯片（文件清单来自产物目录），R2-B 交付卡按版本分组、只显示四类主文件时一并过滤。
- Playwright 的 `structure-document` 与 `analysis-progress` 用例在本机无夹具项目而跳过（与 r2 一致）。
- 第一格的项目目录 `r1-org-hsl` 保留为取证现场（错误工具整场），未删除。
- `test_shelxt_staged::test_grace_exhausted_in_search` 计时抖动仍偶发。
- 两个 MCP 进程同秒冷启动是 Codex 的行为（第二个通常晚几秒并命中缓存），本轮只让它不再致命，没有去改 Codex 的拉起策略。

## 四、全量测试（R1 门禁）

- 全量 pytest：**2355 passed / 25 skipped / 0 failed**（2026-09-05 21:38–21:48，10 min 02 s，`workdir/pytest-full-r3r1.log`，basetemp 在仓库外；含本轮新增 `test_transcript_paging.py` 17 例、`test_concurrent_open.py` 7 例）。
- vitest 283（含取证夹具回放）；`tsc` 干净；`npm run build` 成功（构建 2026-09-05T13:08:48Z，服务器 21:09:47 重启后 `ui_build.stale=false`）。
- Playwright：r3-pre 16 passed / 4 skipped；r3-r1 `reconnect.pw.ts` 3 passed（真实 10 224 行线程）。
- 一格实机：org_hsl 第二次 16 min 38 s / 53 次工具，评分 publication。
- tag `r3-r1-done`。
