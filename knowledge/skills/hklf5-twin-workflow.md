---
name: hklf5-twin-workflow
description: HKLF5 孪晶批次数据的完整工作流：TWINABS 成对导出的分工（_0m_4 求解 / _0m_5 终修）、帧路线自产 HKLF5（export_twin_hklf5 + swap_reflection_data 换数据安全序列）、SHELXT/smtbx 对 HKLF5 的行为边界（实测）、模型换基思路、完整度会计两大静默污点（SHELXL 只数 batch-1；min_isigi×sum 背景负偏签名与 profile 解法；partial 复合建模）。遇到孪晶批次 hkl、BASF 无 TWIN 的模型、帧路线双晶格索引后、或孪晶数据完整度远低于预期时先读此卡。
alerts: []
tools: [ingest_vendor_data, export_twin_hklf5, swap_reflection_data, run_shelxt, solve_charge_flipping, run_shelxl, set_twin, audit_reflection_data]
tags: [孪晶, HKLF5, TWINABS, BASF, 数据换基]
source: p770 战役实战（r10 第 5-8 轮 + hklf5_experiment 三脚本）；SHELXT 行为经 vendor 探针实证（2026-08-30，workdir/shelxt_hklf5_probe）；工具行为对应 r11 的 B3 修复（tools_frames/tools_extra）
confidence: high
created_by: mentor
---

# HKLF5 孪晶批次数据工作流

## 识别与语义

- HKLF5 文件在每行 28 列后带**批次列**：正数 m = 该观测归属域 m；负数 −m =
  该行与后续行是同一复合观测的分量（重叠反射）。最大 |m| = 域数 n。
- **域 1 行常排在文件前部**：只嗅前几十行会漏判（ingest 已改为全文件计数）。
- TWINABS 惯例成对导出：`name_0m_4.hkl`（HKLF4，去孪晶单域，给求解）+
  `name_0m_5.hkl`（HKLF5，复合观测，给终修）。两者 transmission 范围略异
  （.abs 文件里各有一段）。

## 引擎行为边界（全部实测）

| 引擎 | HKLF5 行为 |
|---|---|
| SHELXL | 原生支持：`HKLF 5` + BASF×(n−1)，**不写 TWIN**（域归属在数据里） |
| SHELXT | **硬拒** `HKLF 5` 码（"Bad input file"）；把批次文件谎标 HKLF 4 喂它会"能跑但出垃圾解"（p770 实测 R1 0.42、错群、假分子式，重叠行被当独立反射误读） |
| smtbx refine | 按设计拒绝（诚实门）；进程内视图只保留 batch>0 行，审计/电荷翻转近似可用 |
| 平台 ingest | 跟随所选数据写 HKLF 码：选 HKLF5 → start.ins 自动带 `HKLF 5` + n−1 个 1/n BASF；复制的用户 ins 与数据 HKLF 码不符会给 hklf_mismatch 警告 |

## 标准工作流

1. `ingest_vendor_data(source_dir=…)` 先看候选清单，HKLF5 文件会被标
   `HKLF5-batched` 并报域数。
2. **求解**：用 HKLF4 导出（`hkl='name_0m_4.hkl'`）走 run_shelxt 或
   solve_charge_flipping。SHELXT 对 HKLF5 有护栏会直接拒绝并给路线提示。
3. **终修**：解出模型后，显式重新摄入 HKLF5 文件
   （`ingest_vendor_data(hkl='name_0m_5.hkl', ins=…)` 或走节点），用
   `run_shelxl(mode='adopt')` 精修 BASF。**不要手工往 crystal.hkl 上裸换文件**
   ，p770 事故正源于运行中的 HKLF4 SHELXL 作业底下被换成 HKLF5 数据，
   产出 R1≈0.687 的假象且节点互相污染。换数据 = 显式重摄入 + 新节点。
4. BASF 判读：收敛离 0（如 0.2-0.5）= 第二域真实；两次精修 BASF 漂移
   ±0.01 属正常（同数据同程序不同时期 0.07 vs 0.08 实录），不算复现失败。
5. **权重收敛（HKLF5/TWIN 下 optimize_weights 拒跑是设计使然）**：走
   `set_weights` ← run_shelxl summary 的 `suggested_wght` 闭环，每轮
   run_shelxl 都回传建议权重与 `wght_converged`，不收敛就 set_weights
   采纳再跑，直到建议稳定（r17 实弹教训：无此入口时 GooF 卡 2.5 交付；
   mode='adopt' 会自动采纳建议，check 循环才需要手动 set_weights）。
   收敛判据同样看 summary 的 `shift_esd`（final_max ≤0.05 即收敛），
   restraint 健康看 `disagreeable_restraints`，三者都在返回里，不必
   grep job.lst/job.res。

## 复合超胞陷阱（索引阶段，r17 实弹）

非贯穿孪晶在**无先验自由索引**时的经典歧途：FFT 把两个域一起装进一个
放大的假格子（某轴 ≈ 合理胞边的 2×，如 25.4 Å = 2×12.7）。这个假胞
里往往还能"定出"合理的空间群、精修也能收敛到 0.15-0.2，一切看起来
只是"数据差"。它的物理签名：**大比例重复组严重不一致**（假胞把 A 域
与 B 域的无关强度当等效反射合并，audit_reflection_data 的
duplicates 块会爆表，r17 实测 22.5%）+ 体积/Z 核算翻倍 + |E²−1|
可**超过中心参考 0.968**（复合胞把无关强度当等效合并；audit 工具对
>1.1 有专门警报）。index_frames 现在会自动比对本项目历史索引胞与
厂商先验胞的整数倍体积关系并出 twin_composite_warning - **在索引
阶段就接球**。分辨手段：
用**半胞**做先验重新索引并开 max_lattices=2，真复合胞会干净裂成两个
子格子；再走下节的双域流程。反过来记：索引出的胞若某轴可对半、且
合并统计病态，先怀疑复合胞再怀疑晶体。

## 帧路线自产 HKLF5（export_twin_hklf5，p770 帧全链实证）

原始帧起步、无 TWINABS 时的对应物。前提：index_frames(max_lattices=2,
keep_lattice=主域) 留下 indexed_all（双晶格全 sweep）。

1. `export_twin_hklf5`：双域联合积分→分域独立定标→按 sweep 做预测位置
   重叠三分类→产出 `twin5.hkl`（HKLF5）与 `twin_major_clean.hkl`
   （重叠净化主域 HKLF4，给求解）。三分类语义：完全重合=复合记录
   （blob 总强度）；部分重叠=互相污染、**剔除**（数量必须披露）；
   干净=单域行。
2. 求解用 `create_start_model(hkl_source='twin_major_clean.hkl')`，
   净化主域比污染全量好解得多（p770：R1 0.101→0.065 的主要来源就是
   净化+全 sweep）。
3. 模型立住后 `swap_reflection_data(hkl='twin5.hkl', reason=…)` 换入
   孪晶数据（工具自动备份旧数据、重建 merge、设 BASF 起始、清陈旧
   mask）→ `run_shelxl` 终修。**这是"换数据=显式工具+新节点"纪律的
   合规通道**：上一节的裸换文件事故不会重演。
4. BASF 判读（帧路线特有）：BASF 1 = 复合记录测得的孪晶分数（p770
   0.114(4)，比索引斑点占比 21% 低是正常，斑点计数高估弱域）；
   **若存在 batch 3（minor_policy 补入的次域单线），其 BASF 只是次域
   任意定标的吸收项、不是物理分数，报告里必须写明**。
5. minor_policy 取舍要在报告里交代：none=最优 R 值光学；coverage=
   只按 hkl 身份补主域缺失的独立反射（统计中性）；all=弱域数据全量
   拖高未加权 R1。**注意（E1 实测）：SHELXL 的
   _diffrn_measured_fraction 只统计 batch-1 行，batch-2/3 单线无论
   补多少都不动报告完整度**；它们提供的是真实约束，不是完整度光学。

## 完整度的两个静默污点（p770 E1 对照实验，2026-08-31）

同一批帧，文献 TWINABS 路线 theta_full 完整度 0.962，我们默认参数
交付 0.591，数据实测覆盖其实高达 0.996，损失全在管线两处：

1. **dials.scale 的 min_isigi 卫兵 × 求和背景负偏**。结构化 CCD 噪声
   （或拥挤孪晶花样）会把求和积分的背景估计系统性抬高，弱反射
   I_sum 大片跌破 −5σ（p770 实测中位数 −27σ），而同批行的 prf 强度
   完全健康（中位数 +5σ），combine 选择下 min_isigi 卫兵按 sum 剔除
   了 25% 的行，且弱 unique 的每次冗余测量都弱、按 unique 相关地
   全军覆没。**签名**：export_twin_hklf5 / scale_and_export 返回的
   scaling_exclusions 里 removed_sum_isigi 很大而 removed_prf_isigi
   接近零。**处置**：intensity='profile' 重定标（p770：剔除 4456→485
   行）。健康探测器上 combine 对强反射更准，是否切 profile 看签名，
   不是一律切。
2. **partial_policy='drop' 的系统性丢失**。孪晶重叠模式由固定的
   格子关系决定，被重叠的 unique 在所有冗余测量里都重叠，整类剔除
   后这些 unique 永久缺失，完整度远低于帧的实际覆盖。
   partial_policy='composite' 把部分重叠对写成 TWINABS 式复合记录
   （主域测量当 blob 近似；p770 配对间距 p50=3.4px，blob 近似成立）。
   完整度阶梯实测：0.579(drop+combine) → 0.799(composite) →
   **0.991(composite+profile)**，超过文献 0.962；R1 代价约
   +0.005~0.010。

**代价与披露**：composite 的 blob 近似低估次域尾巴贡献，精修出的
BASF 会明显低于真实孪晶分数（p770：0.11→约 0.05），报告里孪晶
分数要么引用 drop 模式的 BASF，要么明示低估。求解仍然用净化
HKLF4（twin_major_clean.hkl），composite 只影响终修数据。发表
完整度与最干净 R 值不可兼得时，两套导出各跑一次对照、在报告里
披露选择依据，是标准做法。

## 非贯穿双域判例：模型移植三臂判决（r21/r24 同题，2026-09-01）

同一套 Zn 配位聚合物帧（Pna2₁，反演孪晶+180°绕c* 非贯穿第二晶格域）。
r21 交付单域 HKLF4+`TWIN -1` R1 0.1087；r24（平台修复后）双域 HKLF5
走通反而 0.1625；文献 0.0901。**把 r24 的最终模型冻结、只换数据重修**
（模型移植判决法）后真相水落石出：

| 数据 | R1(strong) | Rint | 备注 |
|---|---|---|---|
| DIALS 双域 HKLF5（r24 交付） | 0.1625 | 0.381 | 无 SHEL，0.58 Å 全量 |
| 作者的 twin 还原尝试（0.69 重叠阈值） | 0.1534 | 0.381 | 截 0.81 后 0.1351 |
| 作者的常规单 UB 还原 + SHEL 0.81 | **0.0811** | **0.072** | 优于其发表值！ |
| 文献发表内嵌 hkl+同一模型 | 0.0904 | 0.104 | =文献 0.0901，BASF 0.497=0.496 |

（更正记录：第 2/3 行曾误记为"我们凌晨 LISTEN MODE smoke 产物"，
comm 比对证明全部是作者 2019 实验目录遗留，作者本人也在 twin
与常规还原间反复试验，最终发表用的既非其最佳常规版也非 twin 版。）

**判读链**（每条都反直觉）：
1. **agent 的模型是 publication 级**：在文献数据上逐位复现文献
   R1/BASF。below_bar 判的是数据还原，不是结构测定。评卷时想分离
   两者：把 agent 模型移植到参考数据上重修一发（廉价、决定性）。
2. **文献也没做联合积分**：就是主域 HKLF4+`TWIN -1` 路线（r21 的
   直觉正确）。它赢在还原质量三件套：analytical 吸收校正、成熟
   误差模型/剔除（Rint 0.10 vs 我们 0.34）、**0.81 Å 分辨率截断**
   （我们无 SHEL 全量入修=高角弱反射灌水 R1 约 +0.02）。
3. HKLF5 复合路线在部分重叠严重的非贯穿孪晶上 R1 天然高于"只修
   主域+TWIN"（复合对假设完全重合，部分重叠系统性失配），指标
   难看但更诚实；两条路线各跑一次、披露选择依据。
4. 反演孪晶与取向域并存=潜在 4 分量，但 MoKα 轻原子上反演分量只经
   反常散射影响强度（<1%），别为它上 4 分量 HKLF5。
5. 交付前**分辨率截断纪律**：estimate_resolution 给的建议要真执行
   （SHEL），文献级 R1 都是截断后的数字；同时按 delivery 卡披露截断。

## 模型换基（进阶，p770 实操验证）

HKLF5 文件的指标基可能与当前模型基不同（TWINABS 按域 1 基导出，而模型
可能解在另一套等价胞上）。症状：换上 HKLF5 后 R1 爆到 0.6+ 但结构明明对。
处置：在度规张量上枚举 {-1,0,1}⁹ 单模矩阵找基变换（p770 实例
[[-1,0,1],[0,-1,1],[0,0,1]]），把**模型**变换到数据基（xs.change_basis），
再跑 SHELXL。注意 Niggli 参数相等≠格子同一，两套 setting 可以都满足
约化条件而角度差 3-4°。
