# reg9-dbu：第二轮 R5 端到端一格（草稿）

**实验设计**：与 reg7 完全相同的一格（orgdis_dbu，COD 2241572，B/full 臂，
gpt-5.6-sol @ xhigh，4 核），只换模板与工具面：模板 v36，工具面带第二轮
R2–R5 的全部改动（一份成键真值、相互作用引擎、按节点缓存的分析产物、
`analyze_packing`、`run_shelxl(extra_cards)`、`get_geometry` 三个新 scope、
每个工具描述末尾的参数摘要行、`situation_report` 的阶段与堆积摘要、reg8
四项）。问题只有一个：**agent 会不会调 `analyze_packing`、读懂它、把 HTAB
卡送进 `final.cif`，且不比 reg7 退步？**

**结论先行**：这一格的头条不是评级，是一个 P0 缺陷，`analyze_packing`
的首次调用在 MCP 进程的 worker 线程里做 `import scipy.spatial` 时卡进了
Windows loader lock，35 分钟没有返回；agent 按纪律没有杀进程、把它记成
工具缺陷、换路径继续，最终交付 acceptable。缺陷已定位（py-spy）、已修
（a311653）、已有冷进程回归测试；HTAB→CIF 这一问在本格**没有得到回答**，
留给 reg10-dbu。

所有数字只来自 `workdir/campaigns/reg9-dbu/state.json`、
`dbu-full-r1/grade.json`、`verdict.json` 与交付目录的 `transcript.jsonl`；
缺的字段打 ` - `。

## 1. 结果总表

| 晶体 | 臂 | 等级 | R1(agent) | R1(ref) | ΔR1 | 空间群一致 | 组成 | 诚实门 | 最佳节点是否交付 | 墙钟 | tokens in/out | 工具调用 | 未返回 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dbu | B/full v36 | **acceptable** | 0.0551 | 0.0447 | +0.0104 | 是（P 1 21/n 1） | C15H20N5O6 vs 参考 C16H20N4O6 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF 解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:4 条 | 是（n0074 = 树内最佳，Δ 0） | 58 min | 16,283,912 / 47,766 | 134 完成 | 1（analyze_packing） |

未达 publication 的原因（grade.json 原话）：`R1 delta vs reference 0.0104 > 0.01`。
A 级警报 7 条里 6 条是元数据缺失（183/184/185/197/198/699，不计分），
1 条模型质量（881 无 R_equivalents，预归并 HKLF4 的老问题）。骨架判语
`framework_reproduced`：非 H 28/28 匹配，rms 0.008 Å。

## 2. 与 reg7 同格对照（n=1，只报事实）

| | reg7-dbu（v34/v35 前） | reg9-dbu（v36 + R2–R5 工具面） |
|---|---|---|
| 等级 | publication | acceptable |
| R1 / ΔR1 | 0.0475 / +0.0028 | 0.0551 / +0.0104 |
| checkCIF A/B/C | 7/2/8 | 7/5/9 |
| 墙钟 | 22.7 min | 58.1 min（其中 ≈35 min 在等 analyze_packing） |
| tokens in | 10.24 M | 16.28 M |
| 工具调用 | 236 | 134 完成 + 1 未返回 |
| 组成 | — | 多判了一个 N（C15N5 vs C16N4） |

两格只差一次运行，评级差**不能**归因于工具面：58 分钟里 35 分钟是在等一个
卡死的调用，等待期间 agent 每 2–3 分钟发一条"仍在等待、不杀进程"的消
息（40 条 agent 消息里有 12 条是这个），之后的无序试验、权重收敛与交付
都是在被打乱的节奏里完成的。组成差一个元素（见 §4）与卡死无关，是独立
的化学判断问题。

## 3. 头条：worker 线程首次导入 scipy 的 loader-lock 死锁（P0）

**时间线**（本地时间）：

- 23:31:42 开跑；23:40:35 agent 第一次调 `analyze_packing`
  （`blocks=["interactions"], criteria="platon", only_passing=true`），
  这是本格第一次触发按节点缓存的分析产物构建。
- 23:42–00:15 无任何返回、无进度事件。agent 的原话（转录）："堆积分析已
  明显超过说明中的常见 1–2 分钟，我将把这一超时现象视为工具侧问题记录
  下来；按项目纪律不终止其子进程，也不并发发送会争用同一项目锁的晶体
  学调用。"——这是我们想要的行为：**慢不等于卡死、不得杀子进程、如实
  记录**。
- 00:10 前后我用 py-spy 对 MCP 进程（pid 52540）做 dump：主线程空转在
  selector 里；一个 "AnyIO worker thread" 停在
  `crystalpilot/chem/interactions.py` 的 `import scipy.spatial` →
  `importlib._bootstrap._load_unlocked` → DLL 加载。这与 2026-08 已记录
  的 numpy 规则同源：numpy 与 scipy 各自带一份 OpenBLAS，其 DllMain 起线
  程池，在 anyio 的 stdio worker 线程已经存在时首次加载会与 loader lock
  互等。numpy 早已改成 `anyio.run` 之前导入；scipy 这次是**第一次**在
  worker 线程里被首次导入（R2 相互作用引擎新引入的依赖）。
- 00:15:34 agent 停止等待（"按项目'超过声明预算视为工具缺陷并换路径'
  的要求，我现在停止等待这个前端调用；不使用 shell 杀任何子进程"），改
  调 `get_project_brief` 继续。转录里没有这次 `analyze_packing` 的
  `tool_completed` 事件；交付目录下没有任何 `analysis.json`。
- 00:29:54 评分完成。

**为什么 300 s 预算没有救它**：`analyze_packing` 的 `time_budget_s` 是协作
式的（PLD 二分按预算收敛），对一个卡在 C 层 DLL 加载的线程无能为力；
codex 侧的 `tool_timeout_sec=3900` 也远长于这次等待。

**修法（a311653，已提交）**：

1. `crystalpilot/mcp/prewarm.py`：两份名单。`PRELOOP_MODULES`（numpy +
   scipy 全家：linalg / spatial / spatial.distance / ndimage / sparse /
   sparse.csgraph / optimize）由 `mcp/server.py main()` 在 `anyio.run`
   之前导入；`HEAVY_MODULES`（cctbx / smtbx / iotbx / gemmi 的 boost 扩
   展）在首次 `_ensure` 时于主线程 `prewarm_heavy_imports()`。
   app-server 启动也预热同一份名单。
2. `tests/test_prewarm.py`：ast 扫描 `crystalpilot/` 内所有函数体里的
   scipy / cctbx / smtbx / iotbx / mmtbx / gemmi 懒导入，必须在名单上
   （扫描当场抓出 `cctbx.adp_restraints`、`iotbx.mrcfile`、
   `iotbx.xplor.map` 三个漏网的）；再用**冷进程 + stdio** 真跑一次
   `initialize → tools/list → tools/call analyze_packing`（Ca-imidazolate
   基准），必须在 240 s 内返回（实测整个测试 7 s）。
3. 原有的 `test_cold_cache_list_tools_does_not_deadlock` 在 scipy 被放进
   in-loop 名单时就会复现死锁（120 s 超时），把 scipy 挪到 pre-loop 后
   通过，这就是"scipy 也必须在 loop 之前"的直接证据。
4. 分析产物新增 `timings_s`（四块各自耗时）与构建期心跳，下次再慢就能
   看到慢在哪一块。

## 4. 第二发现：多判一个氮（组成 C15H20N5O6 vs 参考 C16H20N4O6）

骨架 28/28 原子位置全对（rms 0.008 Å），但有一个碳被判成了氮。转录里
agent 的推理是"N2 附近 H1 由差图和删除-回峰/R 升高支持"，并把"形式质
子化/电荷补偿缺少合成先验"列进了未决披露，它知道自己在没有化学先验
的情况下下了元素判断，也如实说了。`audit_element_assignment` 调了两次、
`element_scan` 一次，没有拦住。这不是工具面回归（reg7 的组成列为，，
当时评分器还不报组成），是一条独立的能力边界：**轻原子 C/N 的区分只靠
X 射线密度与几何在 0.81 Å 分辨率下本来就弱**，需要合成先验。交付纪律
上它做对了（披露），结果上它错了（多一个 N，R1 也因此偏高一截）。

## 5. 工具面其余观察（单次运行成立的事实）

- 参数摘要行有效：本格没有出现 reg8 那种"15–33 次 schema 试探"，134 次
  完成调用里没有参数错误重试（`started_not_completed` 只有那 1 次）。
- `situation_report` 调了 5 次、`get_project_brief` 3 次；`branch` 15
  次 / `checkout` 11 次 / `model_disorder` 12 次，无序试验（C00Q、O1/O3、
  C14/C15）占了工具调用的大头，最终采纳 C14/C15 两位 0.71:0.29。
- `run_shelxl` 15 次，全部 `adopt`/`adopt_wght` 模式；`extra_cards`
  通道**一次也没用上**：因为它的 HTAB 卡来源就是没返回的
  `analyze_packing`。`final.cif` 里 `_geom_hbond_` 循环 0 条。
- reg8 四项里可验证的两项：`ingest_vendor_data` 2 次（导入即报重复
  hkl 的路径被走到，无异常）；`model_disorder` 分裂后骑乘 H 复制（转录里
  "17 riding H re-derived" 的注记出现）。其余两项本格没有触发条件。

## 6. 下一步

- **reg10-dbu**（清单已写：`H:/CrystalPilotData/campaigns/reg10-dbu.json`，
  同一格、同一数据、同一模板，只多了 a311653 的修复）：回答 reg9 没答的
  三问，`analyze_packing` 是否在预算内返回并被读懂、HTAB 卡是否进
  `final.cif`、有无回归。
- 元素判断（§4）不在本轮范围；记入能力边界，留给下一轮的"合成先验缺失
  时的轻原子裁决"专题。
