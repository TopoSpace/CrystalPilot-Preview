---
name: flack-absolute-structure
description: Flack 参数判读链：先评判定力（su 大小+Parsons/classical 一致性+反常散射信号强度），再在四种典型情形（≈0 保持 / ≈1 翻转 / ≈0.5 外消旋孪晶 / 无判定力如实披露）间以竞争精修裁决；处置工具链与 su 括号约定；轻原子结构的诚实披露话术。非心群精修后、PLAT032/033/916 警报时、审稿人质疑绝对构型时读此卡。
alerts: [PLAT032, PLAT033, PLAT916]
tools: [run_shelxl, invert_structure, set_twin, validate_structure]
tags: [Flack, 绝对结构, 手性, 外消旋孪晶, Parsons]
source: SHELXL lst 逐字格式（workbench/hklf5_experiment/refined_tol010.lst）；论坛 tid 1405（Flack 空间群争议案，ACS Catal. 2024）、tid 1137（987_B Flack 处置）；checkcif_kb 032/033/916；r11 B1 落地（run_shelxl 自动回读）
confidence: high
created_by: mentor
---

# Flack 绝对结构参数判读链

## 数据来源与格式

run_shelxl 对每个非心群作业自动回读 job.lst 的两行（写进
summary.shelxl.flack* 与节点 metrics）：

```
 Flack x =    1.546(999) by classical fit to all intensities
             -0.431(999) from 857 selected quotients (Parsons' method)
 ** Absolute structure cannot be determined reliably **
```

- 括号 su 是**值末位单位**：`0.0231(212)` → su=0.0212；`1.546(999)` → su=0.999
  （999 常为封顶值=完全无判定力）。
- **优先 Parsons 商法**（对弱反常信号更稳健）；classical fit 作对照。
- 第三行出现即 SHELXL 自判"不可靠"，直接进分支④。

## 判读：先评判定力，再辨情形（数值是证据锚点，不是路由开关）

**第一步永远是判定力评估**: "Flack 正常/异常"必须同时看三件事：
① su 量级：判定力随 su 增大衰减，|x| 与 max(2su, 0.1) 比较是经典准则，
su>0.3 基本无判定力（文献更严锚点：对映纯未知需 su≲0.04、已知对映纯
su≲0.1，Flack & Bernardinelli, J. Appl. Cryst. 2000, 33, 1143）；
② Parsons 与 classical 两估计是否一致（分歧大 = 信号弱或数据有病）；
③ 反常散射信号强度先验（元素种类+波长；轻原子+Mo 靶先验就弱）。
**无判定力的 Flack 什么都排除不了**：既不证明构型，也不能据以排除反演
孪晶（与 framework-twin-pseudosymmetry-alarm 卡口径一致）。

四种典型情形（判定力足够时的证据锚点+竞争精修验证，非按线路由）：

| Flack x 观察 | 首选解释 | 验证与处置 |
|---|---|---|
| ≈0（锚点 \|x\|≤max(2su, 0.1) 且 su≤0.3） | 构型正确 | 核对 Parsons/classical 一致后保持；CIF 正常携带 |
| ≈1 | 模型是对映异构体 | `invert_structure`（按群正确换手：Fdd2 类移位反演、P3₁↔P3₂ 换群自动处理）→ 重跑 run_shelxl 确认归零，翻转前后对照即竞争精修 |
| ≈0.5（锚点 0.3-0.7 且 su 小） | 外消旋/反演孪晶假设 | `set_twin(law='inversion')` → run_shelxl 精修 BASF，与未加孪晶模型对照（R/差图/BASF su）；假设成立则 BASF≈占比、Flack 失义属正常；BASF 修回 0 附近或指标不动则回头查数据质量/吸收 |
| su>0.3 或"cannot be determined" | **无判定力** | 轻原子+Mo 靶属正常物理，不是错误。如实披露"绝对结构未可靠测定"，**不要硬标构型**，也不要以此"正常"排除孪晶；确需测定构型时换 Cu 靶/掺重原子重测 |

中间值（如 0.2±0.03）：先查数据质量与吸收校正，再考虑部分对映体过量或
孪晶，不要直接下结论；两个备择都要以竞争精修/重测证据裁决（实案
tid 1405 见下节）。

## 警报与审稿对应

- **PLAT032**（su 过大）：分支④话术，"weak anomalous signal for a
  light-atom structure with Mo radiation; absolute structure not reliably
  determined"。这是可解释项，不阻发表。
- **PLAT033**（值异常）：按上表处置后复跑；处置过程写进 VALIDATION。
- **PLAT916**（Flack vs Hooft 不一致）：弱信号下两估计器分歧属统计正常，
  说明两者 su 与信号强弱即可（"有合理解释即可"）。
- 审稿人可能拿 Flack 论证换空间群（实案 tid 1405：审稿人称 P1 下
  Flack=-0.004 优于 P21 的 0.214），**不盲从**：先复算审稿人方案，
  复现不出就重测数据；该案新数据 P21 下 Flack 0.214(12)→0.062(3)，
  保住原空间群发表。Flack 差可能是数据质量问题而非空间群错误。

## 纪律

- 孪晶激活时 invert_structure 会拒绝（先 set_twin(law='remove')），
  TWIN 下翻转会静默改变孪晶矩阵含义。
- 翻转后必须重精修并复查 Flack 归零，翻转本身不是终点。
- validate_structure 会在"非心+含反常散射体+无 Flack 记录"时提示补测。
