# 用户会话复盘与交付链路修复（2026-09-08，usertest test3-1 / test3-2）

本文是对两个真实用户会话的复盘，以及由此落实的代码修改与验证记录。
证据均给出可定位的路径；"已证实"与"推测"分开写。会话原始记录在
`H:\CrystalPilot-campaigns\usertest\test3-1-0908`、`…\test3-2-0908`（用户记录，
本次只读；回归在 `H:\cp-pytest-tmp\handover-real\` 的副本上跑）。
回放工具与产物：`workdir/scratch/render_rollout.py`、`workdir/scratch/dump_call.py`，
时间线在 `workdir/scratch/replay/test3-{1,2}{,-full,-compact}.txt`；
D 盘 8010 服务日志解码件 `workdir/scratch/replay/d-service-154252.utf8.log`。

---

## 一、两个会话的主要发现及证据

### 记录完整性（先说缺什么）

| 记录 | 有无 | 位置 |
|---|---|---|
| 前端消息与 AI 决策/工具调用/结果 | 有（codex rollout JSONL） | 回放件 `workdir/scratch/replay/test3-*-full.txt` |
| 节点库（每次改模的模型、指标、数据版本） | 有 | `<project>/.crystalpilot/refine/nodes/nNNNN/{node.json,model.res,model.cif,peaks.json}` |
| SHELXL 作业（ins/hkl/res/cif/fcf/fab/lst） | 有 | `<project>/.crystalpilot/refine/shelxl/job_*/` |
| 反射数据版本 | 有 | `<project>/.crystalpilot/refine/data/dNNNNNN/{observations.hkl,data.json,sources/}` |
| 交付目录 | 有 | `<project>/CrystalPilot Results/task_*/` |
| 后端服务日志 | 有（UTF-16，已解码） | 15883 行 ×200，3×400 是另一项目的 feed，**0 条 traceback** |
| 用户上传的图片 | 有 | `<project>/uploads/`（本次逐张读过） |
| 模型是否真的"看到"图片 | **无法从记录判断** | 见"未证实"项 |

### test3-2（L2 + Zn(BF4)2，P 3₂ 2 1，交付节点 n0077 / 作业 job_20260908_183504）

1. **假门禁：Hall 符号引号解析错误（已证实，根因 A）**
   `P 32 2"` 这类 Hall 符号以 `"` 结尾，`crystalpilot/io/cif_symmetry.py` 的去引号只剥
   一侧，得到的 Hall 与算符组比对不一致 → `check_cif_symmetry` 报 `consistent: False`
   → `finalize_delivery` 当作 fatal 拒绝封存。证据：原交付 `final.cif` 用修复前代码
   检查为不一致、修复后 `{'consistent': True}`；受影响的是全部 12 个含 `"` 的三方/
   菱方群（`tests/test_cif_symmetry_setting.py::test_every_double_quote_hall_symbol_round_trips`）。
   用户看到的现象是"明明对的空间群却说对称性不一致、交付被拒"。
2. **为了拿到 CIF 而动模型（已证实，根因 C）**
   时间线 18:29–18:35：`write_outputs` 因"最近作业与节点不匹配"回落为极简 model.cif，
   智能体于是移动原子、跑一个未收敛周期（max shift/su 40.7）只为得到一个 SHELXL CIF。
   不匹配的直接原因：adopt 之后 riding H 在进程内重算，作业里的 H 坐标与节点 H 坐标
   在第 4 位小数上不同，配对的"坐标全等"腿失败。
3. **诊断性封存被拒（已证实，根因 D）**
   18:39 `finalize_delivery(status=diagnostic)` 因缺 `final.fcf`/`checkcif.json` 被当作
   fatal 拒绝，用户拿不到任何封存记录。
4. **界面显示"—"被读成"精修丢了"（已证实现象，根因 G）**
   几何操作（加删原子/加氢/掩膜/设孪晶）提交的节点没有自己的 R 值，界面显示"—"；
   副本上统计：78 个节点中 36 个无自身 R1。
5. **骨架完整性靠用户反复引导（已证实）**
   用户多次要求"严格保持 n0052 的 Zn2(L2)2 非氢骨架"（见交付 open item
   `goal:scientifically_established` 的目标原文）。属于判断/流程问题：有配体先验时
   应先补全骨架候选再谈指标。
6. **"看不到图片"（未证实）**
   模型称无法读取用户上传的图；记录里能确认图片已入 `uploads/`，但无法确认经
   OpenRouter/GLM 通道时图像是否真的随消息送达。本次不下结论，只把提示改成
   "没收到就直说、不猜图上内容"。

### test3-1（L1 + Zn(BF4)2，R 3 :H，交付节点 n0100 / 作业 job_20260908_184212）

1. **交接文件不是工具产物（已证实，根因 B）**
   课题组的人工接手集是 `res / cif / ins / hkl / p4p`；`write_outputs` 只写
   res/cif/fcf/fab，智能体用 shell 拼：`final.ins` 是 `final.res` 的复制（无 L.S. 卡，
   `shelxl final` 什么都不算）；vendor hkl 原样复制、无 SHELX 终止行（`0 0 0`），
   Olex2 报 "unknown hkl error"；`.p4p` 靠猜文件名从 vendor 目录取。
2. **Olex2 画出七配位锌（已证实，根因 E）**
   `final.cif` 的 `_geom_bond` 里有 `Zn02 C21 2.52 Å` - SHELXL 按固定半径表列键，
   而模型自身成键（`chem.bonding.bond_table`）不认这对；Olex2 按 CIF 画键（20:32
   截图）。修复后审计在真实 CIF 上准确命中此一行（`tests/test_handover_files.py::
   test_real_delivery_flags_the_zn02_c21_row`）。
3. **结构质量本身是诊断级（已证实）**
   R1 0.1736 / wR2 0.4235 / GooF 3.30、掩膜 5215 e⁻/晶胞、Flack −0.01(12)；这不是
   交付链的问题，是要如实交付并标注阶段的结果。
4. **后端无异常（已证实）**
   两个会话期间服务日志 0 条 traceback；工具调用均返回。

### 根因归类与"哪些人工引导可固化"

| 根因 | 类别 | 固化为系统能力 |
|---|---|---|
| A Hall 引号解析 | 质量判断（假阳性） | 修 `cif_unquote`，12 群回归测试 |
| B 交接文件缺失 | 工具能力 | `write_outputs` 产出 ins/hkl/p4p，记录来源 |
| C 极简 CIF 静默回落、配对过严 | 工具能力 + 调度逻辑 | 绑定作业优先配对、容忍 riding-H 重算、零周期作业、带统计块的模型 CIF 并标级 |
| D 诊断封存拒绝 | 交互设计 | 缺 fcf/checkcif/VALIDATION 记为待办项 |
| E 半径表假键 | 质量判断 | `bond_table_audit` + `FREE` 卡白名单 |
| F AGENTS.md 流程文本给不出 ACTA CIF | 上下文传递 | 改为"最后一次改模后 adopt(l_s≥1) → write_outputs"，并写明不为拿 CIF 动原子 |
| G 节点无指标显示"—" | 交互设计 | 沿用最近有测量的祖先，标"沿用 nXXXX" |
| H 图片能力 | 未证实 | 只改诚实表述 |

---

## 二、已确认的根因、优先级和对应修改

优先级按用户给定顺序：数据丢失/版本错配/导出遗漏 → 阻断人工接手 → 未达发表级阻断
交付 → 反复引导的流程问题。

| 优先 | 修改 | 文件 |
|---|---|---|
| 1 | `cif_unquote` 只剥匹配的外层引号；`_quote` 含 `'` 时用 `"…"` | `crystalpilot/io/cif_symmetry.py`，测试 `tests/test_cif_symmetry_setting.py` |
| 1 | 摄入时记录并冻结随 hkl 的 `.p4p/._ls/.abs`（stem 配对 → 晶胞来源文件 → 唯一一个），写入 `context.data.vendor_p4p/…` 与数据版本 `input_context` | `crystalpilot/refine/tools_frames.py`（`_pick_vendor_file`）、`crystalpilot/refine/data_versions.py` |
| 2 | 新模块：`final.hkl`（绑定数据版本字节保真 + 缺终止行时补）、`final.ins`（配对作业 job.ins，否则 res + `L.S. 4/ACTA/…` 重启块）、`final.p4p`（按记录找，找不到如实报"缺失输入"）、模型 CIF 统计块、`_geom_bond` 审计、`manual_continuation` | `crystalpilot/refine/deliver_files.py` |
| 2 | `write_outputs`：产出上述文件；每个文件的来源写入 `REPORT.json files`、`MANIFEST.json provenance`；`summary.manual_continuation / file_provenance / cif_grade / bond_table_audit`；CIF 头第 4 行 `# CrystalPilot delivery cif: <grade> - <说明>` | `crystalpilot/refine/tools_deliver.py` |
| 3 | 配对：节点 `metrics_source.job` 优先且 H 不参与坐标腿（重原子仍须全等）；未配对时先跑零周期 SHELXL（`mode=check, l_s=0`，不提交节点）取该模型的真实 R 值与 fcf；模型 CIF 标级 `model`，统计来源写在文件里 | `tools_deliver.py`（`_job_match_legs`、`_publication_cif`、`_zero_cycle_job`），`deliver_files.enrich_model_cif` |
| 3 | 诊断性交付：缺 `final.fcf/checkcif.json/VALIDATION.md` 为待办项（可封存），缺 `final.ins/final.hkl` 为阻断项，缺 `final.p4p` 记 `missing_inputs`（永不阻断）；`finalize_delivery` 把 `missing_inputs` 写进 REPORT/MANIFEST | `tools_deliver.py`（`delivery_audit`、`FinalizeDelivery`） |
| 3 | `FREE`/`BIND` 进入卡片白名单，审计给出 `FREE <金属> <原子>` 建议 | `crystalpilot/io/shelx_model.py`、`crystalpilot/refine/shelx_cards.py` |
| 4 | `list_nodes` 给无自身指标的节点标注最近祖先的 R1/wR2/GooF（`metrics_inherited`，不并入自身指标） | `crystalpilot/refine/nodes.py` |
| 4 | 界面：结构头 R 值沿用祖先时变淡并标"沿用 nXXXX"；交付卡显示 CIF 等级（"SHELXL ACTA CIF"/"模型 CIF"）与"人工接手文件齐全 / 缺 …"；主文件列表加 ins/hkl/p4p/fab | `ui/src/workbench/crystal/StructureHeader.tsx`、`ui/src/workbench/chat/DeliveryCard.tsx`、`ui/src/lib/delivery.ts`、`ui/src/lib/zh.ts`、`ui/src/lib/wbTypes.ts` |
| 4 | AGENTS.md（v43 / tools-only v5）：交付流程改为"最后一次改模后 adopt(l_s≥1) → write_outputs（产出七件与来源；不为拿 CIF 动原子；审计有嫌疑键加 FREE 重跑）→ checkcif → VALIDATION/SUMMARY → finalize（未达发表级 diagnostic 照样封存）"；判断方式加"有配体先验先补全骨架"；附件表述改诚实 | `crystalpilot/workbench/agents_md.py` |
| 文档 | 架构说明补交付链 | `ARCHITECTURE.md` |

明确**没有**做的：没有只改提示词来掩盖后端缺陷（A–E、G 都是后端/界面代码修改，
F 是补充说明而非替代）；没有删除任何门禁的有效性检查（对称性、原子数/Z/掩膜一致、
`.fab`/ABIN 一致等 fatal 项保持不变）。

---

## 三、五种目标文件：来源、导出方式、完整性检查

以 `write_outputs` 输出目录为准；`REPORT.json.files` / `MANIFEST.json.provenance`
逐文件记录来源，`manual_continuation` 给出可否人工接手。

| 文件 | 数据来源（阶段） | 导出方式 | 一致性/有效性检查 | 缺失时 |
|---|---|---|---|---|
| `final.res` | 交付节点 `model.res`（精修阶段最后模型），掩膜时加 ABIN | 写出 | 原子数/H 数/Z/掩膜与 CIF 一致（既有 `delivery_audit`） | 致命 |
| `final.cif` | 配对 SHELXL 作业 `job.cif` + 会话元数据（ACTA 级）；否则节点 `model.cif` + 本模型的统计块（模型级，头部标级） | 写出；不再静默给极简 CIF | 对称性（Hall 修复后）、R1 与节点一致、坐标/标签一致；模型级统计只来自零周期作业或 `metrics_current` 的自身指标 | 致命 |
| `final.ins` | 配对作业的 `job.ins`（产生这份 cif/fcf 的原始指令）；否则 `final.res` + 标准命令块 | 写出，`inserted_cards` 记录 | 含 `L.S./ACTA/HKLF`，80 列限制 | 阻断项 |
| `final.hkl` | 节点绑定的反射数据版本 `observations.hkl`（摄入阶段冻结） | 字节保真复制；无终止行时补 `0 0 0` 行（换行风格随原文件）；SADABS 尾注保留 | `n_reflections`、`terminator_added`、`trailer_lines`、`data_revision` 记录 | 阻断项 |
| `final.p4p` | 摄入时随 hkl 记录的仪器文件（数据版本 `sources/` → `context.vendor_p4p` → vendor 目录唯一一个） | 复制 | 不可由模型推导；多于一个且未记录时**不猜** | `missing_inputs`（不阻断，REPORT/MANIFEST/SUMMARY 写明原因） |
| （附）`final.fab`/`final.fcf` | 配对作业或零周期作业 | 复制 | 掩膜模型缺 fab 仍是致命（ABIN 无法复现） | — |

"源数据不足" vs "系统有数据却没导出"的区分：p4p 在两个真实会话里都在 vendor 目录
（各恰好一个），属于后者，现在自动导出；旧会话摄入未记录 `vendor_p4p`，靠"唯一
一个"规则找到并如实写明"the only one there"。若 vendor 目录没有 p4p，则是前者，
交付报告 `missing_inputs` 并说明需要用户提供仪器文件。

真实数据回归结果（副本，`workdir/scratch/replay/regression-test3-{1b,2}.log`）：

- test3-1（n0100）：七件齐全；`final.hkl` 11505 条反射、补终止行；`final.p4p` 来自
  `20168A3-L1+Zn-BF4/168A3.p4p`；`final.ins` = job_20260908_184212 的 job.ins；
  对称性检查 `consistent: True`；键表审计命中 `Zn02 C21 2.52`，建议 `FREE Zn02 C21`；
  `finalize_delivery(diagnostic)` 封存成功，待办项 = 缺 checkcif/VALIDATION + 未达目标。
- test3-2（n0077）：七件齐全；`final.hkl` 6.3 MB、原文件已有终止行并保留 SADABS
  尾注；`final.p4p` 来自 `20168A7-L2-Zn-BF4/168A7_1_0m.p4p`；对称性 `P 32 2 1`
  `consistent: True`（修复前为 False）；键表审计 0 嫌疑；封存成功。

---

## 四、发表级门禁修改后的实际行为

- **交付是否完整**与**结构质量是否达标**分开评估：`status=provisional/diagnostic`
  的 `write_outputs` 总是写出全部文件与来源；`finalize_delivery` 对 diagnostic 只把
  `final.fcf / checkcif.json / VALIDATION.md` 记为 open items（封存不推进），对
  provisional 仍要求它们（推进为 final 的门槛不变）。
- 致命项不变：缺 `final.res/final.cif/SUMMARY.md`、掩膜缺 `final.fab`、原子数/Z/
  对称性不一致、checkcif 看的不是这份 CIF。
- 交付的是哪个版本：`REPORT.json.source_state`（节点、修订号）、`job_match`
  （配对到哪个作业、经 `node metrics_source` 还是内容扫描、是否容忍了 riding-H）、
  `cif_grade`。
- 没有有效结构时：输入（数据版本）、中间节点、作业日志都在 `.crystalpilot/refine/`
  下，`write_outputs` 仍可对任一节点产出模型级 CIF + res/ins/hkl。

---

## 五、验证结果

已通过：

- `tests/test_cif_symmetry_setting.py` 48 通过（含 12 个含 `"` 的 Hall 群往返）。
- `tests/test_handover_files.py` 新增 19 项（hkl 终止行/尾注/CRLF、ins 命令块、p4p
  查找四种情形、统计块与幂等、`_geom_bond` 审计合成结构 + 真实 test3-1 CIF、
  `manual_continuation`）。
- `tests/test_finalize_delivery.py` 新增 `TestHandoverSet` 6 项（ins/hkl 来源、配对
  作业 job.ins、p4p 导出、未配对节点的标级模型 CIF、诊断封存缺 fcf/checkcif、
  绑定作业容忍 riding-H 漂移而重原子移动仍拒绝）；交付四套件共 94 通过。
- `tests/test_ingest_candidates.py` 新增摄入 sidecar 记录测试；43 通过。
- 前端：`vitest src/lib/delivery.test.ts` 6 通过；`tsc --noEmit` 通过；`npm run build`
  成功（8010 已重启到新代码，`/api/health` `stale: false`）；Playwright
  `ui/e2e/handover-header.pw.ts` 在 test3-2 副本上通过：几何节点 n0007 的结构头显示
  `R1 0.2616 · wR2 0.5978 · GooF 1.95 · 沿用 n0006 · 待精修`（截图
  `workdir/ui-evidence/usertest-0908/handover-header-inherited-n0007.png`）。交付卡的
  CIF 等级/人工接手行只做了单元测试与类型检查，没有在浏览器里截图（需要一条带新版
  write_outputs 结果的真实对话）。
- 真实数据回归：两个会话副本上 `write_outputs → finalize_delivery` 全链路，见第三节。
- 全量 pytest（仓库外 basetemp，分两段跑）：第一段 `-x` 到 `tests/test_shelx_cards.py`
  为止 2215 通过 / 26 跳过 / 1 失败（卡片白名单精确集合测试没把 FREE/BIND 计入，已更新）；
  第二段剩余 32 个文件 431 通过 / 1 跳过 / 1 失败（AGENTS 模板长度预算 9200，v43 交付流程
  文本超出 279 字符，预算提至 9500，plain 变体仍 < 9000）；两处修后重跑相关文件 83 通过。
  `tests/test_nodestore.py` 加了"几何节点沿用祖先指标"断言（SJTU-9 真实数据）。

无法在本轮验证（如实列出）：

1. **模型是否能看到上传图片**：取决于提供方通道，本次未做模型调用。
2. **零周期作业路径在真实数据上的表现**：两个会话的交付节点都有绑定作业，走的是
   配对路径；零周期路径只在单元测试中以"SHELXL 不可用 → 跳过并如实记录"验证，
   真实 SHELXL 零周期 + fcf 复制未在本轮真实数据上跑（需要一个无绑定作业的节点）。
3. **`FREE Zn02 C21` 重跑后 Olex2 的显示**：卡片被白名单接受并在真实 CIF 上给出
   建议，但没有重跑 SHELXL 验证键表行消失。
4. **原始帧入口**：只检查了共享逻辑（数据版本、摄入 sidecar 记录、交付），没有
   跑帧→hkl 全流程。
5. **交付卡的浏览器级验证**：结构头已截图核实；交付卡（CIF 等级、人工接手行）要等
   一条用新版 `write_outputs` 跑出的真实对话才能在界面里看到。

仍未解决 / 需要的条件：

- test3-1 的结构本身仍是诊断级（R1 0.17、GooF 3.3、掩膜 49% 体积）；交付链现在
  能如实交付它，但化学问题（客体、无序、骨架）需要人工继续。
- `final.p4p` 依赖摄入时 vendor 目录里有该文件；旧项目靠"唯一一个"规则。
- 图片能力问题需要一次带图的真实模型调用来判定。
