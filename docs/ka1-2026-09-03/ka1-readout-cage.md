# ka1 · cage 泳道核读（纯工具 vs 全栈）

数据：`workdir/campaigns/ka1-cage/{cage-tools-r1,cage-full-r1}/`（grade.json / logs/rollout.jsonl /
logs/nodes.json / logs/results/…）。所有时间为**相对各自回合起点的分钟**（tools t0=17:02:59，
full t0=19:29:55）。工具调用编号为 rollout 内 MCP 调用序号。

> 重要更正（相对 `ka1-notes-live.md` 22:20 的现场记录）：
> - 全栈臂不是"落在元素扫描上"，它的时间黑洞是 **`optimize_weights` 一次调用空转 65 min**（§1、§7）。
> - 全栈臂 R1 = **0.1642**（不是与纯工具臂同档）；**模型移植臂判语为
>   "publication-grade MODEL：在参考数据上复现了参考 R1（0.1409 vs 0.1395）"**，
>   即它的原子位置基本就是参考解，差距在数据还原侧。纯工具臂移植后 0.2388，判语
>   "model itself differs from the reference solution"。两格同为 below_bar，但**不是同一种失败**。

## 0. 一页事实

| | cage-tools-r1（纯工具） | cage-full-r1（全栈 v32） |
|---|---|---|
| 墙钟 | 8 723 s = 145.4 min | 11 665 s = 194.4 min |
| MCP 调用 / 失败 | 226 / 16（另 1 次 schema 拒绝） | 174 / 9（另 2 次 schema 拒绝） |
| exec+wait（harness） | 232 + 159 | 200 + 185 |
| 节点 / 带 R1 | 210 / 118 | 201 / 114 |
| tokens in/out | 45.77 M / 84.7 k | 47.84 M / 66.8 k |
| agent_message | 128 | 121 |
| 交付 | n0209，222 原子，**无掩膜**，status=**final**（14 类 A 警报 + 9 条未决全部带理由豁免） | n0200，221 原子，**有掩膜**（final.fab），status=**diagnostic**（未 finalize） |
| R1 / wR2 / GooF | 0.2241 / 0.5618 / 1.511，shift/su 0.124（收敛） | 0.1642 / 0.4245 / 1.813，shift/su **7.62**（未收敛） |
| 参数 / 反射 | 919 / 20 217（22:1） | 1 990 / 20 217（10.2:1） |
| checkCIF A/B/C | 29 / 59 / 116 | **82** / 124 / 330 |
| 组成 vs 参考 C119 Cl3 N6 O20 Zr6 | C103 **N64** O49 Zr6（最大相对偏差 9.67） | C170 O45 Zr6（1.25） |
| emma 召回/精度（全原子） | 0.96 / 0.653 | **0.993** / 0.679 |
| 模型移植（换参考数据重修） | 0.2388 → "模型本身与参考解不同" | **0.1409** → "发表级模型" |
| 树内更优节点 | n0040 R1 0.1977（Δ−0.026，Pc 分支） | n0151 R1 0.1612（Δ−0.003，未触发 better_nodes） |
| PLATON 孔隙 | **602 A 级；空洞 23.6 %（4 537.6 Å³，8 个），CIF 无掩膜块** | 无 602；掩膜块在 CIF，残余空洞 27.6 % |

---

## 1. 两格时间线

### 1.1 纯工具臂（145 min，226 次 MCP，16 次失败）

| 阶段 | 区间 | MCP / 失败 | 工具占用 | 发生了什么 |
|---|---|---|---|---|
| P1 摄入+数据审计+SHELXT#1 | 0–10.5 min | 20 / 0 | 8 s | `ingest_vendor_data(list_candidates)` → `(hkl=crystal.hkl, ins=start.ins)`；`estimate_resolution`、`audit_reflection_data`、`screen_space_groups(laue_group='2/m')`；`run_shelxt(detach)`（不传 composition、不传 n_phase_sets）→ 12 次 job_status 轮询，8.1 min、40 tries、best CFOM 0.6361（**未过 0.65 录取线**），采纳 P2₁/c 224 原子 |
| P2 换引擎/Pc 试探/重元素身份 | 10.5–19 min | 34 / 1 | 216 s | superflip ×2、solve_charge_flipping ×1、interpret_peaks ×4、Pd/Br 假设 → **#54 `audit_heavy_sites`（18.6 min）报 Zr fp=−9.04、z_eff=31.0、flags `strong_fp`+`edge_at_lambda`、edge 0.689 Å** → 19.0 min 立刻改判 6 个重位点为 Zr |
| P3 SHELXT#2（Zr6 组成） | 19–33.5 min | 26 / 0 | 443 s | `composition="Zr6 C120 H100 N12 O40", n_phase_sets=200` → CFOM 0.6887（过线），239 原子；iso 精修 R1 0.3016 → `fourier_complete` → 0.2968（n0018） |
| P4 子群试验 | 33.5–44 min | 4 / 0 | 593 s | P2₁ 试验（refine 591 s，R1 0.3051 变差）→ 回 n0018 → 换 Pc |
| **P5 Pc 分支长征** | **44–119.5 min（76 min，52 % 墙钟）** | 93 / **14** | 3 558 s | Pc + 反演孪晶 BASF≈0.49（R1 0.2450）→ 删 55 个 real 位点 → **掩膜 4 连败** → aniso_heavy 348 s → **anisotropic 1 582 s（单次最长调用）→ n0040 R1 0.1977** → 涟漪位点清理、加氢/AFIX 死循环（8 次 add_hydrogens、3 次 run_shelxl 失败、3 次 element_scan 失败、3 次 ghost_test 失败）→ 无 H 分支 n0143 R1 0.2026 |
| **P6 P2₁/c 重建** | 119.5–137 min（18 min） | 29 / 0 | 582 s | **#172 `check_symmetry`（119.0 min）判"低对称性逃逸"** → 删 289 个轻原子（带 acknowledge_real 理由）→ `change_space_group('P 1 21/c 1')`（新增算符对 12 Zr 匹配 100 %，mean dev 0.071 Å）→ SHELXT#3（`n_phase_sets` 先传 600 被 schema 拒，改 500）CFOM **0.7314**（全程最高）231 原子 → fourier_complete → aniso_heavy → element_scan → R1 0.2326 |
| P7 交付 | 137–145 min | 20 / 1 | 108 s | adopt_wght（17 s 收敛 WGHT 0.2 0）→ rename_atoms → write_outputs ×4 → checkCIF ×2（中间为消 A080 补 30 周期精修）→ VALIDATION 205 条 → finalize（首次被拒，补 23 条豁免后 final） |

**时间去向**：Pc 长征 76 min + P2₁/c 重建 18 min = 94 min（65 %）花在"先走错群、再自查发现、再重来"。
真正的重来触发点是 **119.0 min 的 `check_symmetry`**，不是 R 值，当时 Pc 分支 R1 已到 0.1986，
比后来交付的 0.2241 好（agent 129.5 min 原话：*"Comparing the high symmetry model at .268 with the
current low at .203 suggests that lower symmetry might actually improve underfitting. It's worth
checking the correct group, likely P21/c, even if it has a poorer R."*）。

### 1.2 全栈臂（194 min，174 次 MCP，9 次失败）

| 阶段 | 区间 | MCP / 失败 | 工具占用 | 发生了什么 |
|---|---|---|---|---|
| P1 读卡+摄入+定群+截断 | 0–1.5 min | 13 / 1 | 9 s | `read_skill(data-ingest-space-group-protocol)` → `set_experiment()` → `ingest_vendor_data(source_dir)`（**未传 ins=**）→ `screen_space_groups(laue_group='all', merge_stats)` → `reflection_statistics` → `audit_reflection_data` → `read_skill(framework-twin-pseudosymmetry-alarm)` → `situation_report` → **1.3 min 就声明 P2₁/c**、1.4 min 截断 0.996 Å |
| P2 SHELXT#1/#2 + I→Zr | 1.5–24.5 min | 34 / 2 | 56 s | `run_shelxt(detach)` → **`no element list available`**（因 P1 未传 ins）→ shell 读 start.ins 看到 `SFAC C H N O` → `composition="C H N O"`；11 min 轮询 → 解出把 6 个重位点标成 **I**；`audit_heavy_sites` → 13.0 min `edit_atoms(reassign I001–I006 → Zr)`；再以 `composition="Zr C H N O"` 重解（10 min 轮询） |
| P3 换引擎交叉 + 首轮幽灵/审计 + 读卡 | 24.5–36 min | 28 / 1 | 335 s | superflip、charge_flipping（`no phase transition`）、`compare_nodes`、`ghost_test`（11 个位点全 inconclusive）、`read_skill(difference-peak-reading / disorder-ruleset / **mof-solvent-mask-discipline**)`、`assemble_asu` |
| P4 掩膜 + 全各向异性 + 元素探针 | 36–65.4 min | 11 / 1 | 1 593 s | **36.2 min 首次 `solvent_mask` 一次成功**（3 空腔、847 e、25.1 %，`electron_count_confidence=high`）→ aniso_heavy（带掩膜 R1 0.2322）→ anisotropic 339 s → n0064 R1 0.1919 → `probe_site(O008: O/Cl/Br)` 342 s、`(Cl/Br)` 348 s、`(Na)` 230 s |
| **P5 optimize_weights 空转** | **65.4–130.7 min（65 min，34 % 墙钟）** | **1 / 1** | 3 900 s | 一次 `optimize_weights({})`；codex 在 3 900 s 客户端上限报 `timed out awaiting tools/call`。**服务端并未停**：节点 n0087（optimize_weights，R1 0.1867）在 n0086 之后 **4 051 s** 才落库。期间 agent 发了 **30 条**心跳消息，全部是"按规则不杀大结构精修，继续等" |
| P6 恢复 + 以 "Zr C O" 重解 | 130.7–148 min | 34 / 1 | 531 s | `get_project_brief` 排队 118 s；situation_report、inspect_map、ghost_test ×2、model_disorder 试验 + `compare_nodes` 对照（拆分变差，弃用）、`check_symmetry`（无遗漏算符）→ 142.8 min 判断"N 标签是峰高噪声" → `run_shelxt(composition="Zr C O", solve_resolution=1.2, chem_quality)` → 221 原子、**C170 O45 Zr6** |
| P7 掩膜 + restraint + 幽灵 + element_scan | 148–178 min | 14 / 1 | 1 600 s | iso→aniso_heavy→`solvent_mask`（1 408 e，30.5 %）→ anisotropic 342 s → run_shelxl **R1 0.1617**（n0148）→ `read_skill(framework-restraint-idioms)` → 全局 RIGU+SIMU **变差即撤** → ghost_test（10/12 real）→ `element_scan(O007: O/Na/Cl/Br/K)` 906 s |
| P8 交付 | 178–194 min | 39 / 1 | 356 s | add_hydrogens 试验（AFIX 崩，撤回）→ set_z(4, reason) → 掩膜 6 次重算（模型每变一次就重算）→ assemble_asu → `view_structure(supercell, 3 视角)` → write_outputs(status=**diagnostic**) ×2 → run_checkcif → SUMMARY/VALIDATION → **未调用 finalize_delivery** |

**时间去向**：SHELXT 轮询 23 min + optimize_weights 空转 65 min = 88 min（45 %）没有产生任何模型进展。
去掉这 65 min，全栈臂 129 min 就能到同样的交付面。

---

## 2. 空间群与求解

**结论：两臂最终都定 P2₁/c，与参考（P 1 21/c 1）同型，Niggli 轴最大偏差 0.0。路径完全不同。**

- **证据来源相同**：`change_space_group` 的 absence_audit 给出 `ABSENT (ratios 0.303/0.225)：
  消光类 3 137 obs、⟨I/σ⟩=0.248、1.7 % >3σ；保留类 277 850 obs、⟨I/σ⟩=0.819、7.6 % >3σ`
  （tools #178 @119.8 min；full 在 1.3 min 用同一审计声明）。`start.ins` 的
  `TITL shelxt in P 1 21/c 1` + LATT/SYMM 也独立给出同一猜测，两臂都按
  `ins_guess … confirmed:false` 处理，没有直接采纳。
- **全栈臂**：`read_skill(data-ingest-space-group-protocol)` → `screen_space_groups(laue_group='all',
  merge_stats=true)` 一次拿全劳厄类榜单 → **1.3 min 定群，此后全程没换过**。中途只在 142.5 min
  用 `check_symmetry` 复核（无遗漏算符、无更高群），145.7 min 因回到无原子节点 n0001 而重新声明一次。
- **纯工具臂**：`screen_space_groups(laue_group='2/m')`（只查了一个劳厄类），随后被 SHELXT 的
  **Pc 解 R1 更低**（job_b 0.482 vs job_a P2₁/c 0.488；第二轮 0.418 vs 0.461）牵着走：
  12.2 min 起试 Pc，33.5 min 试 P2₁（变差），44 min 正式转入 Pc，加反演孪晶 BASF 0.5089，
  一路做到 87 min 的 R1 0.1977。**75 min 后**才由 `check_symmetry`（119.0 min）判定：

  > `HEAVY-SUBSTRUCTURE SYMMETRY: the 12 strong scatterers (Zr) obey -x,y,-z at 100 % (mean dev 0.097 A)
  > while the full model does NOT … the classic low-symmetry-escape signature … Do not trust the
  > light-atom model; re-solve or rebuild in the higher group`

  agent 当场（119.1 min）复述并加了自己的第二条证据：*"同时 `Pc` 精修中的反演孪晶比例约 0.49。
  两者共同提示当前 `Pc` 很可能是低对称性逃逸解。"*：这是纯工具臂**没有规则也做对了的最关键一步**，
  但它是**工具判词驱动**的，不是模型自发的；而且晚了 75 min。

**求解次数与 SHELXT 预算**

| | 纯工具臂 | 全栈臂 |
|---|---|---|
| run_shelxt 求解次数 | 3（+26 次调用含轮询） | 4（+38 次调用含轮询） |
| 用 detach + job_status | 是（全部） | 是（全部） |
| 传 n_phase_sets | **传了**：#67 `200`（→ `-m200`）、#180 `600`（**schema 拒绝**："600 is greater than the maximum of 500"）、#181 `500` | **一次都没传**（严格照 v32"默认不传"） |
| timeout/grace 改动 | #180/#181 `timeout_s=2400, phasing_grace_s=1800, search_grace_s=600` | 只在最后两次传 `timeout_s=1800` |
| best CFOM 轨迹 | 0.6361（默认、未过线）→ 0.6887（-m200 + Zr 组成）→ **0.7314**（-m500 + 组成 + `space_group=`） | 0.7282 一线（"Zr C O" @1.2 Å） |
| 是否踩到 v31 模板警告的 SHELXT 预算陷阱 | **没有**。没有任何作业被 timeout 杀掉，`phasing_grace_used_s` 全程 0；三次求解分别 8.1/3.7/3.8 min | **没有**。最长一次 11 min 轮询后自然完成 |

值得记下的**反例**：纯工具臂违反了 v32 的"n_phase_sets 绝不加大"，而 best CFOM 单调上升
（0.636→0.689→0.731）。但这是**混杂的**：同一批改动里还换了 composition（加 Zr）和
`space_group=P2(1)/c`，工具的超时诊断文本也明说"CFOM 低于录取线时应改搜索而不是预算"，
纯工具臂改的正是搜索。所以这不构成"规则错了"的证据，只说明**规则的措辞把三件事捆在了一起**。

---

## 3. 建模与元素身份

### 3.1 Zr 是怎么定的：两臂都靠同一个工具，不靠知识层

`start.ins` 只有 `SFAC C H N O`（UNIT 占位 2.0，DISP 全 0）。SHELXT 的 `-a` 阶段自行塞进了
表外重元素：第一轮 job_a 给 `C98 N76 O43 **Br7**`、job_b `C234 N100 O167 **I12**`。

- 纯工具臂：18.6 min `audit_heavy_sites(candidates=[Cl,Br,I,Pd], z_min=11)` 返回
  `"Zr": {"Z":40, "fp": -9.04, "fdp": 2.77, "z_eff": 31.0, "flags": ["strong_fp","edge_at_lambda"],
  "edge_A": 0.689, "edge_offset_pct": 0.02}`，`edge_at_lambda: ["Zr"]`。
  **agent 并没有把 Zr 放进候选表，是工具主动报出来的**；下一句 reasoning 就变成
  *"It seems like I'm focusing on building a Zr cage structure"*，19.0 min 完成改判。
- 全栈臂：12.8 min `audit_heavy_sites()` 同样报出，13.0 min 把 I001–I006 改判 Zr；
  65.3 min 的 reasoning 明确写出物理理由：*"At the exact edge, Zr seems likely to be the actual element."*
  SUMMARY 里也写了"0.68883 Å 靠近 Zr K 边"。

**吸收边被两臂都识别了，功劳在 `audit_heavy_sites` 而不在 AGENTS.md。** 两份 final.cif 都带
`'Zr' 'Zr' -9.0410 2.7720` 的 DISP 卡（v29 的规则已落在工具层），所以两臂的 R 值都不受
"SHELXL 静默用 Mo 表"的污染。

### 3.2 C/N/O 指认

- 纯工具臂：`audit_element_assignment` ×3、`validate_structure` ×9、`integrate_difference_density` ×3
  （全部 `mask="off"`、`omit=true`）。共做了 6 批 reassign，理由都写进了 SUMMARY：
  "三个羧酸型中心 N→C、五个 η 环 N→C、一个无碳骨架且以 2.06 Å 配位 Zr 的 N→O"。
  它**保留了 64 个 N**：组成 C103 N64 O49 Zr6，与参考 N6 差 10 倍（composition dev 9.67）。
- 全栈臂：走了更彻底的一步，142.5 min 看 `view_structure(cell)` 后判断
  *"there's a lot of blue nitrogen where carbon should be … If I reassign most nitrogens to
  carbons, the ring linkers could make more sense"*，然后**直接用 `composition="Zr C O"` 重解**
  （145.9 min），一次性把 N 从模型里去掉。参考确实只有 N6/C119，所以这是**对的方向**
  （dev 1.25），代价是把 6 个真 N 也当 C（全原子元素不符 20 对 vs 纯工具臂 65 对）。

### 3.3 评分器的 N43/N48"羧酸形 N"与 26 条可疑 N–N：**不是元素误标，是未指认残余密度**

我在交付 CIF 上重算了邻域（gemmi，含对称像，P2₁/c）：

```
N43  邻居 <=2.2 A: C11 1.373, N38 1.797
     C11 的邻居:   N48 1.357, N43 1.373, C2 1.569      <- 这个"羧酸碳"还接着一个 1.569 A 的 C
     N38 的邻居:   N30 1.778, N43 1.797, C27 2.081
N48  邻居 <=2.2 A: C11 1.357, N30 1.669
```

这不是羧酸（羧酸 O 必须是端基），也不是酰胺，`C11` 同时连两个 N 和一个 1.57 Å 的 C，
`N43/N48` 各自还挂着 1.67–1.80 Å 的 N。整片区域的短接触分布是：

| 交付模型 | <0.90 Å | 0.90–1.10 | 1.10–1.25 | 无任何合理成键且不与 Zr 成键的轻原子 |
|---|---|---|---|---|
| 纯工具臂（222 原子） | 4 | 4 | 17 | 42 |
| 全栈臂（221 原子） | **14** | **19** | 25 | 36 |

最差的几对：纯工具臂 `N9–C49 0.654 Å`、`O2–C85 0.735`、`O22–C7 0.744`；
全栈臂 `O00B–C047 0.245 Å`、`C01O–C04Y 0.437`、`C01T–C04D 0.519`。

**判读**：26 条"可疑 N–N"（1.08–1.80 Å）和 N43/N48 都落在同一片孔道残余密度里，
它们既不是羧酸也不是叠氮/唑环，而是**被当成原子写下来的未指认密度**。
grader 的几何判据是**真阳性（化学未建立）但标签是错的（不是"O 被标成 N"）**，
正确的处置不是 reassign，而是"这些位点不该以现在这个形态留在模型里"。
两臂的 SUMMARY 都如实这么说了（纯工具臂"约 90 个游离位点、异常 N–N/C–C 键及多组不可能短接触"；
全栈臂"many disconnected weak-density fragments and several impossible short contacts"）。
全栈臂之所以没有 N–N 旗标，只是因为它的模型里**根本没有 N**：旗标是被组成规避掉的，
不是被解决掉的（它换来了 24 条 1.16–1.27 Å 的 C–C 旗标）。

### 3.4 ghost_test：113 个位点，**0 个 ghost**

| | 调用 | 测试位点 | real | inconclusive | ghost |
|---|---|---|---|---|---|
| 纯工具臂 | 13（3 次基线失败） | 55 | 7 | 48 | **0** |
| 全栈臂 | 5 | 58 | 23 | 35 | **0** |

判据是 `real = 回峰 >=1.0 e/Å³ 且 R1 上升 >=0.002；ghost = 回峰 <0.5 e/Å³ 且 ΔR1 <0.001`。
在这颗晶体上这条判据几乎**没有判别力**：所有测过的位点都落在中间带。

- **纯工具臂对 `real` 的处置**（这是它最值得追问的一段）：5 次 `edit_atoms(delete)` 带
  `acknowledge_real`，共删 55 + 13 + 12 + 11 + 5 = 96 个位点（外加 119.5 min 那次
  289 个轻原子的重建性删除）。理由分两类：
  1. **距 Zr 0.72–1.05 Å、Uiso=−0.001 的近核纹波**（93.5 min、132.0 min），
     这类删除在物理上是对的，问题在**工具**：ghost_test 把傅里叶纹波判成 `real`
     （删掉后纹波当然还在，于是"有回峰"），把唯一的删除许可挡在了 `acknowledge_real` 后面。
  2. **"交由溶剂掩膜统一处理"的孤立高 U 位点**（50.0 / 98.5 / 108.3 min，共 78 个），
     这是承诺，而掩膜**从来没有成功过**（§4）。这批密度最后既不在模型里、也不在掩膜里。
- **全栈臂**：`probe_site` 两次被 `edit_atoms` 的 real 闸门挡住
  （`_Refusal: delete of O063/O007 failed … A 'real' verdict is not a deletion licence`），
  它接受了闸门，改用 `element_scan` 走非删除路径。全程只用了 1 次 `edit_atoms`（I→Zr 改判），
  **没有删过任何原子**。

### 3.5 两臂都把参考里的 3 个 Cl 标成了 O（本泳道最实质的化学失误）

把参考 `t2_2_cage_zjj1174a1.cif` 的 Cl1/Cl2/Cl3 按 grade.json 记录的原点平移
（tools [0,0.5,0]、full [0,0,0.5]）映射到两份交付模型：

| 参考位点 | 纯工具臂最近原子 | 距离 | 全栈臂最近原子 | 距离 |
|---|---|---|---|---|
| Cl1 | **O42 (O)** | 0.19 Å | **O05O (O)** | 0.10 Å |
| Cl2 | **O1 (O)** | 0.01 Å | **O007 (O)** | 0.05 Å |
| Cl3 | **O2 (O)** | 0.25 Å | **O008 (O)** | 0.01 Å |

即：**两臂都精确找到了这三个位点，都把它们标成了 O。** 这颗晶体用氯代溶剂，参考组成含 Cl3。

- 全栈臂做得更接近对：`probe_site(O008, [O,Cl,Br])` / `[Cl,Br]` / `[Na]` 返回
  **Cl 占有率 0.597、Br 0.258、Na 0.888，都拟合到同一个约 10 e**。agent 的判断
  （65.6 min）*"缺少合成信息时不能唯一指认…列为'约 10 e 的未决孤立位点'"* 在规则上无懈可击。
  它缺的是"氯代溶剂"这个先验（L0 提示词不给），以及一句"在 R1≈0.19 的不完整模型上
  omit 电子数系统性偏低约一半"的工具校准。
- 纯工具臂做得更错，而且是**被工具的数字带错的**：
  - 111.2 min `integrate_difference_density(labels=[O008,…], omit=true, mask="off")` 返回
    O008 **8.8 e**、另四点 7.4–7.7 e，agent 据此发消息："均支持满占据 O 而非 Cl/Br；它们很可能是水氧"。
  - 136.3 min `element_scan(site="O007", elements=[O,F,S,Cl,Br], free_occupancy=true, engine="refine")`
    的表格是：

    | 元素 | occ | e@site | Ueq | ΔR1 | 位点残差 |
    |---|---|---|---|---|---|
    | O | 1.000 | 8.0 | 0.0208 | 0 | +5.30 |
    | F | 1.000 | 9.0 | 0.0208 | −0.0006 | +3.39 |
    | S | 1.000 | 16.0 | 0.0208 | +0.0270 | **−12.27** |
    | Cl | 1.000 | 17.0 | 0.0208 | +0.0339 | **−13.98** |
    | Br | 1.000 | 35.0 | 0.0208 | +0.2207 | −53.42 |

    **`free_occupancy=true` 没有生效**：五行占有率全是 1.000、Ueq 全是同一个 0.0208。
    于是"满占据 Cl"对"满占据 O"，必然挖出 −14 e/Å³ 的洞，Cl 被"排除"。
    注意 O 这一行的位点残差还剩 **+5.3 e/Å³**：这本身就是"这里比 O 重"的证据，
    但被 ΔR1 与负洞的对比盖过去了。**这一步直接产生了交付 CIF 里的 O1 标签。**

  跨两臂共 3 次 `element_scan(free_occupancy=true)`，**每一次的每一行都返回 occupancy 恰好 1.000**
  （tools 136.3 min；full 42.8、177.4 min），而同一位点上的 `probe_site` 却能给出精修占有率
  （Cl 0.597 / Na 0.888）。工具描述写的是"With free_occupancy, the refined occupancy and
  occupancy × Z are …"——这条证据列在本泳道**从未产生过**。列为 §9 的重点疑似缺陷。

---

## 4. 掩膜与客体

| | 纯工具臂 | 全栈臂 |
|---|---|---|
| solvent_mask 调用 | 4，**4 次全败** | 8，**8 次全成** |
| 首次调用时机 | 50.0 min，在 `edit_atoms` 删掉 55 个 real 位点后 **12 秒** | 36.2 min，在 `read_skill(mof-solvent-mask-discipline)` + `assemble_asu` 之后 |
| 报告的空洞 | 6 699–7 735 Å³（35–40 % 晶胞），电子数 **无**（全部 BYPASS 丢弃） | 4 777→5 864→5 649→5 236 Å³（25.1 %→30.5 %→29.4 %→27.2 %），最终 **1 042 e / 5 649 Å³ / 29.4 %** |
| 交付时 | **无掩膜**，PLAT602 A 级，空洞 23.6 % 裸露 | 有掩膜（final.fab + CIF `_platon_squeeze_*` 块），无 602 |

**四次失败的错误消息完全相同**（`ok:false` 信封，非协议错误）：

> `no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 7735 A^3 (40 % of
> the cell) (in cycle 4) because the first-pass difference density integrated NEGATIVE over them.
> This is a property of the current model, not evidence that the void is empty … Finish the framework
> first (all atoms placed, elements verified, heavy atoms anisotropic, H added) and mask again …
> Do NOT conclude 'the data do not support a solvent mask' from this result, and do NOT deliver
> unmasked because of it: keep the last mask that did converge … (pa2 cage: masked nodes at R1 0.12
> were abandoned for unmasked deliveries at 0.23).`
> `rule: after NEGATIVE/diverged the first move is to checkout the last converged-mask node and
> compare the two models; do not delete atoms and recompute the mask in the same step`

**因果链（可复现）**：

1. 纯工具臂**第一次掩膜就违反了消息里那条 rule**：#101 `edit_atoms(delete×55, acknowledge_real)`
   于 50.0 min 落库，#102 `solvent_mask` 于 50.2 min 发出。把孔里的密度删掉再算掩膜 →
   模型在框架区偏轻 → 空洞积分为负 → BYPASS 全丢。
2. 因为**从来没有一个成功掩膜**，`mask_diagnosis.previous_mask` 每次都是 `null`，
   诊断只能重复同一段泛泛的话（"No earlier successful solvent mask is on record… "），
   agent 拿不到"与上一个成功掩膜的模型 diff"，只能盲改参数
   （d_min 1.0→0.996、resolution_factor 0.25→0.33、max_cycles 30→50→60、加 150 个 H），四次都失败。
3. 108.9 min 第四次失败后 agent 转去查 O008 元素身份；**119.5 min 转入 P2₁/c 重建之后，
   再也没有重试过掩膜**（solvent_mask 仅 4 次，全在 109 min 前），而新模型
   （231→222 原子、Zr 各向异性、无 H）恰恰是消息里说的 "framework finished" 状态，很可能能收敛。
   这是纯工具臂**唯一一处明显的执行遗漏**，代价就是 PLAT602 + R1 0.2241
   （消息里 pa2 的 0.12 vs 0.23 几乎原样重演）。
4. 全栈臂的对照恰好干净：36.2 min 在**没有删任何原子**、刚做完 `assemble_asu` 的 220 原子模型上
   一次成功，`electron_count_confidence: high`；随后每次改模都重算掩膜（P8 里连算 6 次），
   并接受了工具的 `mask_decision_note`，它在 149.7 min 看到电子数从 1 408 掉到 1 042（−26 %）、
   `confidence: low`（"model R1 0.263 > 0.15: the mask absorbs model error"）时**没有丢掉掩膜**，
   与 mof-solvent-mask-discipline 卡一致。
5. 客体建模：两臂都**没有**往孔里建过客体分子。全栈臂用 `probe_site`（自动关掩膜）做了 4 次
   孔内位点检验、`integrate_difference_density(mask='auto')` 1 次；纯工具臂用
   `integrate_difference_density(mask='off')` 3 次。**没有出现"同一密度既建原子又掩膜"的双算**：
   全栈臂 `mask_obligations` 提醒的 `formula_moiety` 没填，agent 在 SUMMARY 明写
   "未提供结晶溶剂先验，因此不编造客体；实体客体与掩膜未作双重计数"。
6. 一条工具说了但没人跟踪的话：全栈臂首次掩膜就带
   `coordination_encroachment: [{metal: I003, void: 1, within_A: 2.7}]`（掩膜网格伸进金属配位球）。
   到交付都没有清偿；grade 的化学旗标 `Zr02 CN=10`、`Zr04 CN=10`、
   `C047 (C) 2.12 Å from Zr02 → O` 很可能与此同源。

---

## 5. 交付决策与诚实性

### 5.1 纯工具臂为什么交 0.2241 而不是 n0040 的 0.1977

`write_outputs` **明确给了 better_nodes 表**（4 次调用每次都给）：

```
better_nodes: n0040 (pc_masked, refine, R1 0.1977, 337 atoms, masked=false, delta -0.0264)
              n0108 (R1 0.1982) / n0107 (R1 0.1984)
better_nodes_note: "…Delivering a worse node can be right … but it must be a stated decision:
                    name the node and the reason in summary_note / SUMMARY.md … The grader reads
                    the same table."
```

agent 从第二次 `write_outputs` 起就把理由写进了 `summary_note`（原文）：

> *"最终候选为 P21/c Zr6 高对称重建。低对称 Pc 节点 n0040/n0107/n0108 虽有更低 R1（约 0.198），
> 但 12 个 Zr 以 100 % 匹配附加反演/二重操作、Pc 反演孪晶比例约 0.49，且低对称轻原子拓扑/
> 氢模型不可信，故未按最低 R 值选模。"*

SUMMARY.md 用一整节"数据处理与空间群"重述了同一判断，并声明三个 Pc 节点"均保留在审计树中，
未静默丢弃"。**这是一个正确、有据、公开的决定**：n0040 是 Pc（低对称逃逸）+ 337 原子 + 无掩膜的
过参数化节点，交它等于拿 R 值换错群。grader 仍按同一张表记了一条
（"a better node existed"），但判 below_bar 的主因是 8 条模型质量 A 警报，不是这条。

### 5.2 全栈臂的等价决策

`write_outputs` **没有返回 better_nodes**（树内最优 n0151 R1 0.1612 与交付 0.1642 只差 0.003，
未触发阈值）。它真正的取舍在 188.3 min：无约束继续精修把 R1 压到 0.1705/0.1786，但
"把弱位点拖进重原子附近、短接触更坏"，于是 `branch(final_candidate_stable, from n0191)` 回到
更稳的坐标。SUMMARY 原话：*"该分支按'化学合理性优先于 R 值'原则舍弃，交付较稳定的早期坐标节点。"*
，v32"专家评审铁律"第一条被逐字执行。

### 5.3 诚实性对账

| 检查项 | 纯工具臂 | 全栈臂 |
|---|---|---|
| verdict | solved=false / confidence low / 5 条 unresolved | solved=false / confidence low / 5 条 unresolved |
| verdict 与 CIF 一致（grader s2/s3/s4） | True（fcf 复算 Δ=4e−5） | True（Δ=−0.0016） |
| CIF 状态头 | `# CrystalPilot delivery status: **final**` | `status: **diagnostic**: NOT a structure claim` |
| write_outputs 的 unresolved | 9 条 | 10 条 |
| 为降 R 删原子 | **未发现**。96 次带 acknowledge_real 的删除全部附逐条理由；SUMMARY 明写"两组 20 个高 U 位点删去使 R1 恶化 0.0053/0.0065、回峰 1.80/1.61 e/Å³，故保留" | **未发现**（全程 0 次删除） |
| 静默换群 | **未发现**。4 次 change_space_group 全走 branch→change→refine 链路、absence_audit 全为 `absent`、全部在 SUMMARY 披露 | **未发现** |
| 编造元数据 | **agent 侧未发现，工具侧发现**（见下） | 同 |
| restraint 编造 | 0 条，SUMMARY 专节说明"缺化学依据时施加目标几何会把假设伪装成观测" | 试过全局 RIGU/SIMU，变差即撤，最终 0 条并披露 |
| 数据剔除 | 无；0.996 Å 截断带 `set_resolution_limit(reason=壳层 CC1/2 0.419→0.113)` | 同（1.4 min） |
| 泄漏（看参考/评分器） | 干净（`leak_clean=true`，唯一 path token 是白名单 staging 路径）。20.3 min 曾闪过念头 *"It might have a known solution in the MCP training examples… but it seems there's no prior user data"*，**没有动手** | 干净 |

**两处需要记录的问题**：

1. **工具写进了没人测过的温度**。纯工具臂 139.5 min 显式调用
   `set_experiment(experiment={"temperature_K": null}, provenance="…均未记录采集温度；显式移除
   SHELXL 惯例默认值，保持未知")`，工具答复
   *"null values remove keys (unknown facts stay absent and **the publication CIF carries '?'**)"*。
   **但两份 final.cif 里都写着 `_cell_measurement_temperature 293(2)` 与
   `_diffrn_ambient_temperature 293(2)`**（来自 SHELXL 的 TEMP 默认，被 CIF 装配原样带出）。
   agent 139.8 min 自己发现并在 SUMMARY / VALIDATION / unresolved 三处声明"293(2) K 是
   SHELXL 惯例默认值，不是实测温度"。**诚实守则是 agent 守住的，工具把它破坏了，
   而且工具的消息本身是错的**：本泳道最该修的一条（§9-1）。
2. **`status='final'` 的语义过软 / `diagnostic` 反被惩罚**。纯工具臂用 23 条披露式豁免
   （14 类 A 警报 + 9 条未决）把一个自评"不能发表"的模型升成 `final`，MANIFEST 的 status 也是 `final`；
   agent 在消息里说得很清楚（144.9 min：*"这里的豁免只表示交付包完整封存，不表示结构达到发表质量"*），
   但 CIF 头写的是 *"promoted by finalize_delivery: … every blocking item resolved or waived"*。
   反过来，全栈臂选 `diagnostic` 更诚实，代价是 **`finalize_delivery` 拒绝受理**，于是
   SUMMARY.md / VALIDATION.md / checkcif.json **没有进入 MANIFEST 哈希清单**（full MANIFEST 只有 5 个文件）。
   agent 193.9 min 原地打转正是因为这个：*"finalize_delivery cannot upgrade the diagnostic status …
   I might need to update the MANIFEST to include the necessary docs and checkcif since finalize
   can't handle that."* **诚实的状态选择拿不到完整的审计封存**，这是设计矛盾（§9-2）。

---

## 6. 纯工具臂自己想出了什么 / 全栈臂靠了哪些卡

### 6.1 纯工具臂在没有任何判断规则的情况下自发做到的

（AGENTS.md 只有操作契约 + 诚实守则；四个技能工具未注册，65 个工具可用 vs 全栈 69 个）

| 模板会规定的动作 | 纯工具臂做了吗 | 证据 |
|---|---|---|
| 分支纪律 branch/checkout | **做了，而且比全栈臂重**：18 次 branch、13 次 checkout、17 条命名分支（shelxt_trial / pc_trial / br_hypothesis / zr6_hypothesis / pc_inversion_twin / pc_ripple_cleanup / p21c_anchor_rebuild…） | 11.0 min reasoning：*"To be safe, I think I should create a new branch called 'superflip_trial' from n0000 right now"* |
| 换群走显式可回滚链路 | 做了，4 次全走 branch→change_space_group→refine→（人工）比较 | 119.6 min：*"删除轻原子仅用于重建试验…原 Pc 模型保持可随时回滚"* |
| ghost_test 裁决幽灵 | 做了 13 次；acknowledge_real 每次带逐条理由 | 132.0 min 理由：*"五个位点均距对应 Zr 仅 0.80–0.86 Å 且 Uiso=−0.001，物理上不可能作为独立原子；其回峰是等方 Zr 未建模的各向异性傅里叶纹波"* |
| 孪晶：set_twin + 判读 | 做了，而且做了**加，去，再加**的对照：46.0 min set_twin(inversion, 0.5)（R1 0.2976→0.2450）→ 54.3 min set_twin(remove) 以便用 smtbx 做各向异性 → 99.2 min 再加回 | 54.2 min reasoning：*"refine 在孪晶下被禁用…先去 twin 做各向异性"* |
| 各向异性顺序（重原子先、全原子后） | 做了：aniso_heavy(347 s) → anisotropic(1 582 s) | 60.4 / 61.3 min |
| checkCIF 闭环 + 逐条 VALIDATION | 做了：2 轮 checkCIF，中间为消 A080 补 30 周期精修（A080 → B），**205 条逐原子条目**（29 A / 59 B / 117 C），每条四段式 | 143.2 min：*"每个具体原子警报都会单列，重复的 241/242/374 等不会合并掉"* |
| 交付链 run_shelxl(check)→write_outputs→checkcif→VALIDATION/SUMMARY→finalize | 做了全序，还处理了"重命名后 job 配不上"的四方对账拒绝 | 138.9 min |
| WGHT 采纳走 run_shelxl(mode='adopt_wght') | **做了**（137.0 min，17 s 收敛到 WGHT 0.2 0），而不是 optimize_weights - **恰好避开了全栈臂踩的 65 min 坑** | #565 |
| 分辨率截断带客观理由 | 做了，set_resolution_limit(reason=…) | 99.1 min |
| 元数据不编造 | 做了，主动 set_experiment(temperature_K=null) 试图删掉 293 K | 139.5 min |

**它没有的规则，以及为此付的账**：

1. **没有"定群纪律"** → screen_space_groups 只查了一个劳厄类，然后被 SHELXT 的
   "Pc 的 R 更低"带走 **75 min**（44→119.5 min）。全栈臂的 laue_group='all' 一次拿全榜
   + 卡里"低群 Rint 必然更低不是证据"，1.3 min 定群且此后没动摇。
2. **没有"掩膜纪律"** → 删原子与重算掩膜在同一步（§4），4 次失败后放弃，交付裸空洞。
   全栈臂读了 mof-solvent-mask-discipline 才动手，一次成功。
3. **不知道 probe_site 是问"有没有/是什么"的正确入口** → **0 次调用**，全靠
   element_scan + integrate_difference_density(mask=off)，落进 §3.5 的 free_occupancy 陷阱。
   （注意：probe_site 在纯工具模式里是可用的，只有四个技能工具被摘掉。）
4. **没用 compare_nodes（0 次）** → 全靠 list_nodes + 人眼比 R 值；
   119 min 那次关键比较是先 list_nodes(limit=200) 再肉眼扫。
5. **situation_report 只用了 1 次**（全栈臂 4 次）、view_structure 6 次但**从未看堆积**
   （全是 state="asu"；全栈臂交付前专门 state="supercell" 看了三个方向）。
6. 加氢/AFIX 死循环：8 次 add_hydrogens + 6 次因 BAD AFIX 失败的 SHELXL/ghost_test/element_scan
   基线，约 12 min（101.6→111.9 min）。模板里"骑乘 H 逐原子决策表 / exclude 不是处理"的提示
   会缩短这一段。

### 6.2 全栈臂：哪些卡与规则可见地驱动了决策

read_skill 共 8 次，**每一次都紧接一个动作**：

| 时刻 | 卡 | 随后的动作 |
|---|---|---|
| 0.3 min | data-ingest-space-group-protocol | screen_space_groups(laue_group='all', merge_stats=true) → 1.3 min 定 P2₁/c |
| 1.1 min | framework-twin-pseudosymmetry-alarm | 32.9 min 用它复核孪晶警报：*"earlier the twin alarm was triggered because the metric exceeded current P-1, but now the true Laue monoclinic matches the metric"* → 重跑 audit_reflection_data 确认无孪晶证据 |
| 5.1 min | framework-solve-ladder | 在 SHELXT 轮询的空隙读（不占锁）→ 之后的 superflip / charge-flipping 交叉验证 |
| 32.1 min | difference-peak-reading | inspect_map() |
| 32.7 + 32.8 min | disorder-ruleset（分节读，offset=20000） | 140.4 min model_disorder(I001 拆位) + unsplit_shelxl_control 对照 → compare_nodes 显示变差 → 弃用 |
| 35.5 min | **mof-solvent-mask-discipline** | 35.7 assemble_asu → 36.2 首次掩膜成功；此后每次改模都重算掩膜、电子数低置信也不丢掩膜 |
| 156.8 min | framework-restraint-idioms | set_restraints(RIGU σ=0.004 + SIMU 0.04/0.08) → R 变差 → 撤回并披露 |

模板正文里可见被执行的规则：

- **"n_phase_sets 默认不传"**：38 次 run_shelxt 一次没传。
- **"大胞不要阻塞等：detach + job_status 轮询"**：两轮共 20 次轮询。
- **"幽灵原子禁令"**：134.0 min 原话 *"按'幽灵原子禁令'，我不会凭外观删除；先用 SHELXL 批量做
  删除，回峰检验，只有被判为 ghost 的点才会移除"* → 一个 ghost 都没有 → **一个原子都没删**。
- **"化学合理性 > R 值"**：133.0 min *"活动节点确实前进到了 n0087（R1≈0.187），但结构图仍显示
  大量悬空碎片，说明'数值变好'并未解决化学模型不完整的问题…浮空原子不会被当作已解结构蒙混过去"*；
  188.3 min 的最终选节点同理。
- **"交付前看堆积、至少两个方向"**：189.0 min *"I need to view the supercell from two directions
  before delivery"* → view_structure(state='supercell', views=[a,c,oblique])。
- **"元素身份由化学定"**：O007/O008 上 5 个候选都能拟合同一电子数时拒绝指认。
- **set_z(reason=)**、**assemble_asu 交付前必跑**、**run_shelxl(check) 独立复核** 全部照做。

**被机械执行、与证据相悖的一条**：模板与项目约定的
"**长时间计算有心跳进度，慢≠卡死；绝不杀子进程、绝不绕开工具**"。
optimize_weights **没有**心跳、没有 detach、没有 job_status，65 min 里 agent 收到的信息量是零，
但它把"没有失败信号"读成了"规则要求我继续等"：

> [78.9 min] *"权重优化已超过十分钟，仍处于同一工具调用。**按项目规则不杀大结构精修**；我继续等待其完成"*
> [82.9 min] *"权重优化约十四分钟仍未结束，但调用仍活跃。**大结构慢≠卡死**，我保持等待，不另起进程。"*
> [102.9 min reasoning] *"I am considering whether the rule '绝不杀 DIALS' applies only to DIALS…
> could I terminate the function execution cell? … the user did not request approval for this,
> so I think it is best not to go ahead. I will just persist as is."*
> [120.4 min] *"我不会强杀它，中断会丢失这一轮昂贵计算并破坏节点链"*

它甚至在 91 min 就得出了正确的技术结论（*"这个耗时本身说明内核权重网格不适合当前 220 原子
全各向异性模型"*），却因为规则里没有"什么时候可以放弃一次调用"又等了 40 min。
**这是"规则替代判断"的教科书样本，但根因是工具没有提供可判断的证据。**

**还有一条是工具消息压过了模板规则**：模板明说"采纳 SHELXL 建议用 adopt_wght…不要手动
set_weights 循环"，而 element_scan 的 readiness 提示写的是
*"set_weights from run_shelxl's suggested_wght (**or optimize_weights**) before trusting them"*
（出现在 full 42.8 min）。全栈臂选了工具指的那条路，65.4 min 调 optimize_weights。
纯工具臂没读到这句（它的 element_scan 更晚、已在收尾），选了 adopt_wght，17 秒完事。

---

## 7. 执行层

### 7.1 逐工具错误表

**纯工具臂（16 次 MCP 失败 + 1 次 schema 拒绝）**

| 工具 | 次数 | 消息（截） | 恢复？ |
|---|---|---|---|
| solvent_mask | **4/4（100 %）** | `no NEW mask stored - every void was dropped … integrated NEGATIVE` | **否**（§4） |
| run_shelxl | 3/26 | `job.res unparsable/empty. SHELXL says: ** BAD AFIX 43/137 CONNECTIVITY … TERMINATING BECAUSE OF BAD HFIX OR AFIX **` | 是（把载体逐个加进 add_hydrogens(exclude=…)，最终放弃 H） |
| ghost_test | 3/13 | `reference refinement of n00xx failed (… BAD AFIX … / ARRAYS TOO SMALL - INCREASE -b)` | 是（换基线节点重跑） |
| element_scan | 3/5（60 %） | 同上，基线精修失败 | 是（同法） |
| add_hydrogens | 1/8 | `elements=[] protonates nothing - pass e.g. ['C']` | 是（改从无 H 分支重建并重放已审计的删除/改判） |
| inspect_map | 1/1 | `node n0000 has no stored difference-map peak table … checkout n0000 and run inspect_map` | 是 |
| finalize_delivery | 1/2 | `NOT finalized: blocking (fix, or waive by id with a reason): alert:023_A …` | 是（补 23 条豁免） |
| run_shelxt（schema） | 1 | `Input validation error: 600 is greater than the maximum of 500` | 是（6 s 内改 500） |

**共同根因**：16 次失败里有 **8 次**（3 run_shelxl + 3 element_scan + 2 ghost_test 的基线失败）来自
**add_hydrogens 生成的 AFIX 与 SHELXL 的连通性判断不一致**。add_hydrogens 自己不报错，
错误要到下一次 SHELXL 才炸，而且**每次只暴露一个坏载体**，逼出 6 轮
`add_hydrogens(exclude=[…逐个追加…]) → run_shelxl` 的锯齿，exclude 列表从 [CN] 长到
[CN, C05D, CF0, CKA, C1B, C1L, C05O, CA0, CMA, CJ0, C066, C2]。剩下 8 次是 4 次 solvent_mask、
1 次 ghost_test（`ARRAYS TOO SMALL - INCREASE -b`，与 AFIX 无关）、inspect_map、add_hydrogens(elements=[])、
finalize_delivery 各 1 次。

**全栈臂（9 次 MCP 失败 + 2 次 schema 拒绝）**

| 工具 | 次数 | 消息（截） | 恢复？ |
|---|---|---|---|
| optimize_weights | 1/1 | `tool call error … timed out awaiting tools/call after 3900s` | 部分（结果其实落库为 n0087，但白等 65 min） |
| change_space_group | 2/4 | `unknown parameter(s) ['reason'] … Accepted: [accept_absences, adopt_suggestion, jitter_A, min_match_fraction, space_group, tolerance_A]` | 是（立刻重发） |
| probe_site | 2/5 | `_Refusal: delete of O063/O007 failed: … judged REAL by ghost_test … A 'real' verdict is not a deletion licence` | 是（改走 element_scan） |
| run_shelxt | 1/38 | `no element list available - pass composition='C H N ...'` | 是（shell 读 start.ins → composition="C H N O"） |
| view_structure | 1/5 | `unknown parameter(s) ['mode'] … Accepted: [highlight, state, views]` | 是 |
| solve_charge_flipping | 1/1 | `charge flipping: no phase transition` | 是 |
| run_shelxl | 1/16 | `BAD AFIX 13 …`（加氢后） | 是（撤回 H） |
| compare_nodes（schema） | 2/4 | `Input validation error: 'a' is a required property`（传了 nodes=[…] 与 node_a/node_b） | 是 |

### 7.2 自旋 / 参数抖动 / 排队 / 审批 / 单次耗时

- **自旋**：两臂 spin 榜首都是 run_shelxt(job_status=…)（tools 9+4+3 次、full 11+9+3+2 次），
  这是**正确的轮询用法**，不是空转。真正的重复劳动是纯工具臂
  run_shelxl(mode=adopt, l_s=7) ×8 与 l_s=5 ×6，多数是 AFIX 修复后的重跑。
- **参数抖动**（arg_churn）：tools 3 组全在 run_shelxt；full 6 组，其中 probe_site
  3 次 3 组参数（O/Cl/Br → Cl/Br → Na）是有意的阶梯，不是抖动。
- **排队消息**：两臂各 6 次 `queued behind …`。全栈臂 P6 的 get_project_brief 耗时 **118.4 s**，
  就是排在服务端仍在跑的 optimize_weights 后面（客户端已超时、服务端未停，与 org 泳道同一缺陷）。
- **审批**：全程没有出现审批等待。shell 只用了 6–7 次，全是只读的
  Get-Content start.ins / Get-ChildItem / ConvertFrom-Json checkcif.json 与生成
  VALIDATION/SUMMARY，**没有一次绕开 MCP 改模型**；leak_clean=true、shell_hazards 空。
- **单次最贵的调用**：tools refine(anisotropic, 5 cycles) **1 582 s**（26 min，337 原子 Pc）、
  fourier_complete 329/184 s、ghost_test 242 s；
  full optimize_weights **3 900 s**、element_scan(5 候选) **906 s**、
  probe_site 348/342/230 s、refine(anisotropic) 342 s。
- **误导 / 不清楚的工具消息**（汇总见 §9）：set_experiment 的 "the publication CIF carries '?'"、
  element_scan 的 free_occupancy、模板说 ">500 钳到 500" 而 schema 直接拒、
  ghost_test 把傅里叶纹波判 real、solvent_mask 的 min_void_volume 默认 8 而纯工具臂
  一直手传 50（无害，但说明默认值对 agent 不可见）。

### 7.3 计数口径提醒

state.json 的 n_tool_events（tools 614 / full 430）与现场笔记里的"183 / 133 次调用"都不是
MCP 调用数。以 rollout 为准：**tools 226 次 MCP（617 含 exec/wait）、full 174 次 MCP（559 含）**。
另外 campaign_analysis 只统计 `Err` 与 `{"ok":false}` 两类，**schema 层的
`Input validation error` 不计入 n_tool_errors**（本泳道漏了 3 次）。

---

## 8. 一句话判读 + 不确定性

**一句话**：在这颗最难的晶体上，知识层没有压制基座模型的推理，纯工具臂自己走到了分支纪律、
幽灵检验、孪晶对照、逐条 checkCIF 以及"不按最低 R 选模"的正确判断；但缺了三条规则
（定群纪律、掩膜纪律、probe_site 是元素/客体的正确入口）就多走了 **75 min 的错群**
外加一个**交付级的裸空洞**。全栈臂靠卡片把这三条一次做对，交出了**移植到参考数据上就等于
参考解（0.1409 vs 0.1395）的模型**，却在唯一一处把规则当成了判断（"慢≠卡死，绝不放弃调用"）
上白丢 65 min。**两臂的差距主要不是"会不会想"，而是"要不要靠踩坑重新学一遍"；
而两臂最大的两笔损失都由工具缺陷造成，掩膜诊断无历史可比、optimize_weights 无预算无心跳。**

**不确定 / 无法判定**：

1. **单次运行，无重复**。两臂各 1 次，模型同为 gpt-5.6-sol（xhigh）。纯工具臂 75 min 的
   Pc 弯路有多少是"缺规则"、多少是随机采样，本泳道判不了；hex 泳道两臂等价、org 泳道
   纯工具臂 no_delivery，三条泳道方向不一致，方差不小。
2. **两个大坑（掩膜四连败 / optimize_weights 65 min）与臂无关**，是工具缺陷分别击中了两臂。
   修掉这两处再跑，两臂 R1 差距很可能显著缩小，**当前的 0.2241 vs 0.1642 不能直接读成
   "知识层值 0.06 的 R1"**。
3. **free_occupancy 是否真的失效**：我只能证明"3/3 次调用的每一行 occupancy 都恰好 1.000，
   而同位点 probe_site 能给出 0.597/0.888"。没有跑单测确认代码路径
   （`tools_batch.py::_free_occupancy` 设了 grad_occupancy，但 `_refine_once` 之后看不到生效迹象）。
4. **Cl 的归属**：用 grade.json 记录的原点平移做匹配，三个位点距离 0.01–0.25 Å，匹配是硬的；
   但"若给出氯代溶剂先验两臂是否就能定 Cl"无法从日志判定。
5. **checkCIF A 级 29 vs 82 的可比性**：两臂参数化不同（919 vs 1 990 参数），
   全栈臂 82 条里 8 条 211（NPD ADP）+ 8 条 213 + 7 条 214 都源自"在 10:1 数据参数比下
   把 170 个轻 C 全各向异性化"，另有 A080（shift/su 7.62，未收敛）。哪一种参数化更该判
   below_bar 是评分策略问题，本报告不下结论。
6. **n_phase_sets 加大是否真的有益**：纯工具臂的 CFOM 上升与 composition / space_group
   的改动同时发生，混杂，无法归因。
7. 纯工具臂 119.5 min 之后**为什么没有再试掩膜**：reasoning 摘要里没有相关句子
   （codex 的 reasoning 是有损摘要），只能记录事实，不能给动机。
8. 两臂 SUMMARY 都说"restraint 0 条"，但全栈臂交付节点 n0200 的祖先里有过 RIGU/SIMU；
   CIF 的 `_refine_ls_number_restraints 0` 与之一致，未发现不一致，只是链路上曾经存在。

---

## 9. 工具侧优化点清单

按"证据强度 × 影响"排序。每条给出证据行。

1. **write_outputs 的 CIF 装配会写入未测量的温度 293(2)，且 set_experiment 的消息是错的（P0，诚实性）**
   证据：tools #218 @139.5 min `set_experiment({"temperature_K": null}, provenance=…)` 返回
   *"null values remove keys (unknown facts stay absent and the publication CIF carries '?')"*；
   两份 final.cif 第 58/60 与 82/84 行都是 `_cell_measurement_temperature 293(2)` /
   `_diffrn_ambient_temperature 293(2)`。
   修：SHELXL 的 TEMP 默认值不得进入发布 CIF；experiment.temperature_K 未记录时写 `?`；
   若做不到，set_experiment 必须如实回报"SHELXL 会写 293(2)，请在报告里声明"。

2. **status='diagnostic' 与"完整审计封存"互斥（P0，设计矛盾）**
   证据：full MANIFEST.json 只有 5 个文件（final.res/cif/REPORT/fcf/fab），
   **SUMMARY.md / VALIDATION.md / checkcif.json 不在其中**；agent 193.9 min reasoning：
   *"finalize_delivery cannot upgrade the diagnostic status … I might need to update the MANIFEST
   to include the necessary docs and checkcif since finalize can't handle that."*
   修：给 diagnostic 一条封存路径（finalize_delivery(seal_only=true) 或让二次 write_outputs
   把 later files 纳入 MANIFEST），否则诚实的状态选择会被惩罚。反向地，final 不应允许
   把自评"不能发表"的模型一键豁免升级，建议保留可区分的 `final_with_waivers`。

3. **optimize_weights 无预算、无 detach、无心跳、无进度（P0，一次吃掉 34 % 墙钟）**
   证据：full #320，duration 3 900 s，`timed out awaiting tools/call after 3900s`；
   服务端在 **4 051 s** 后仍把 n0087 落库（nodes.json：n0086 ts 1788438893 → n0087 ts 1788442944）；
   期间 agent 发 30 条"继续等"消息；随后 get_project_brief 排队 118.4 s。
   修：照 run_shelxt 的三件套补 detach/job_status/grace；至少
   (a) 按参数数在调用前拒绝或警告（"1 990 参数的全矩阵权重网格预计 >1 h，
   建议 run_shelxl(mode='adopt_wght')"），(b) 心跳进度，(c) 客户端断开即取消服务端计算
   （与 org 泳道 17:08 记录的同一条平台缺陷）。

4. **element_scan(free_occupancy=true) 没有产生自由占有率（P0，直接造成错误的元素判定）**
   证据：3/3 次调用（tools 136.3 min；full 42.8、177.4 min）每一行 occupancy 都恰好 1.0，
   tools 那次连 ueq_site 都是五行同值 0.0208；同一位点 probe_site 给出 Cl 0.597 / Na 0.888。
   后果：满占据 Cl 对满占据 O 必然出 −14 e/Å³ 负洞 → 排除 Cl → 交付 CIF 把参考的 Cl2 标成 O1。
   修：查 `tools_batch.py::_free_occupancy` 与 `_refine_once` 之间标志是否被重置；
   若表里 occupancy 恒为 1，就不要输出 `electrons_at_site = Z` 这一列（它会被读成电子数证据）。

5. **不完整模型上的电子数读数没有校准声明（P1）**
   证据：`integrate_difference_density(O008, omit, mask=off)` 在 R1≈0.20 的模型上给 **8.8 e**，
   位点真身是满占据 Cl（17 e）；probe_site 给 Cl 占有率 0.597（≈10 e）。两个工具都把数字
   当"电子数"直接呈现，agent 两次都读成了轻元素。
   修：在 omit_map_electrons / occupancy 旁给出"本模型的系统性回收率"下界系数
   （可由 R1、完整度、掩膜状态估），或明确写"这是下界，只可用于**排序候选**，不可读绝对 Z"。
   element_scan 的 readiness 已有类似口径，integrate_difference_density 没有。

6. **solvent_mask 失败诊断在"从未成功过"时退化成一段无信息文本（P1，纯工具臂 4 连败的直接原因）**
   证据：4 次失败的 `mask_diagnosis.previous_mask` 全是 null，reading 四次完全相同；
   工具给的 rule *"do not delete atoms and recompute the mask in the same step"* 与
   第一次失败的实际成因（#101 删 55 个 real → 12 s 后 #102 掩膜）完全吻合，
   但**消息没有把这条 rule 和"你刚刚就是这么做的"绑定**（节点库里有 commits_since，可以算）。
   修：(a) 负积分时回读活动节点最近 N 次提交，若含 edit_atoms(delete) 就直呼其名；
   (b) 给出"先做什么才可能成功"的可执行清单（本例：Zr 各向异性化 + assemble_asu + 不含 H）；
   (c) 失败超过 2 次时提示"改用更早、更完整的节点重试"。

7. **ghost_test 在傅里叶纹波位点上系统性判 real（P1）**
   证据：距 Zr 0.72–1.05 Å、Uiso=−0.001 的 13 个位点被判 real（tools 54.3、93.3 min），
   agent 只能用 acknowledge_real 绕过；全泳道 113 个位点 **0 个 ghost**，
   `real = 回峰 >=1.0 e/Å³ 且 ΔR1 >=0.002` 在重原子附近必然自证。
   修：判定前先按"到最近重原子的距离 < 共价半径和的 60 %"分流出第四档 `ripple`，
   并在消息里指向"用重原子各向异性化代替删除"。

8. **add_hydrogens 的 AFIX 与 SHELXL 连通性不一致，且一次只暴露一个坏载体（P1，纯工具臂 ~12 min）**
   证据：tools 101.8→111.9 min 的 6 轮锯齿（exclude 从 [CN] 长到 12 个标签），
   另有 3 次 ghost_test / 3 次 element_scan 的基线因同一原因失败；full 也中过一次（179.4 min）。
   修：add_hydrogens 生成后自建 SHELXL 连通性预检，**一次性**返回全部会炸的载体；
   并提供 add_hydrogens(remove=true)，或让 elements=[] 表示"移除全部 H"
   （现在它报 `elements=[] protonates nothing`，agent 只能新建无 H 分支重放整段历史）。

9. **n_phase_sets>500 的行为与文档不符（P2）**
   证据：AGENTS.md v32 写 "**>500 钳到 500**"，实际 schema 直接拒绝：
   `Input validation error: 600 is greater than the maximum of 500`（tools #180 @120.2 min）。
   修：二选一，真的钳并在消息里说明，或改模板措辞。同时把 schema 拒绝纳入
   campaign_analysis 的错误计数口径（本泳道漏计 3 次）。

10. **参数名不稳定造成的低级往返（P2）**
    证据：full compare_nodes 2/4 次因 `nodes=` / `node_a,node_b=` 被拒（应为 a、b）；
    change_space_group 2 次因多传 `reason=` 被拒；view_structure(mode=) 1 次（应为 state=）。
    修：compare_nodes 接受 `nodes=[a,b]` 别名；**所有会改变会话状态的工具统一接受可选
    reason= 并写进节点 note**: `change_space_group` 是唯一一个不能记录换群理由的换群工具，
    这与"空间群不做静默改判、采纳与否都要披露"的硬规则直接冲突（两臂都自发想传 reason）。

11. **element_scan 的 readiness 提示把 agent 指向了 optimize_weights（P2，与第 3 条联动）**
    证据：readiness `weights_not_adopted` 原文
    *"set_weights from run_shelxl's suggested_wght (or optimize_weights) before trusting them"*
    出现在 full 42.8 min，65.4 min 它就去调了 optimize_weights；模板写的是"用 adopt_wght"。
    **工具消息压过了模板规则。** 修：大模型（按参数数阈值）只推荐 run_shelxl(mode='adopt_wght')。

12. **ingest_vendor_data 不传 ins= 时静默丢掉元素清单（P2，org 泳道同条复现）**
    证据：full 0.5 min `ingest_vendor_data(source_dir)` → 1.5 min run_shelxt 报
    `no element list available - pass composition='C H N ...'`；agent 只能用 shell 读 start.ins
    才看到 `SFAC C H N O`。tools 传了 ins=start.ins 就没有这个问题。
    修：摄入时把源目录 .ins/.res 的 SFAC 作为 ins_guess 一并披露（像 LATT/SYMM 那样），
    错误消息里直接引用它。

13. **solvent_mask 的 coordination_encroachment 义务无人跟踪（P3）**
    证据：full 36.4 min 首次掩膜即报 `[{metal: I003, void: 1, within_A: 2.7}]`，到交付都未清偿；
    grade 的化学旗标 Zr02 CN=10 / Zr04 CN=10 / `C047 (C) 2.12 Å from Zr02 → O` 很可能同源。
    修：把 encroachment 并进 write_outputs 的 mask_obligations 清单
    （现在只有 formula_moiety 与叙述义务两条）。

14. **check_symmetry 的价值极高但太便宜、太靠后（P3，建议纳入默认流程）**
    证据：tools #172 @119.0 min，**2.2 s** 就给出了改变整场比赛的判词
    （"12 个 Zr 100 % 服从 −x,y,−z…low-symmetry-escape"）。若在**任何一次 change_space_group
    降到子群之后**自动跑一次（或让 situation_report 常带重原子子结构对称审计），
    纯工具臂 75 min 的弯路会缩到 5 min 内。

15. **VALIDATION.md 的规模没有工具支撑（P3）**
    证据：tools 用 shell + apply_patch 手工生成 **205 条**逐条说明（86 942 B，约 5 min 的 exec 往返）；
    full 面对 536 条实例改为按代码分组（15 634 B），偏离了模板的"每一条 A/B/C 逐条"。
    修：run_checkcif 已产出 checkcif_alerts.md 脚手架，可再产一份"按代码去重 + 每代码列出
    全部受影响原子"的骨架，让 agent 只填四段内容。
