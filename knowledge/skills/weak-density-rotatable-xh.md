---
name: weak-density-rotatable-xh
description: 弱密度可旋转 X–H（OH/COOH/配位水）的处置判据：omit 峰 <~0.5 eÅ⁻³、AFIX 扭转轮间翻转、负/NPD Uiso、重精修转回碰撞，任两条同向即"数据不约束该 H 取向"，删坐标、计式量、如实披露，不再拉锯。平台边界（smtbx 不吃 H-DFIX、SHELXL adopt 不回放自由 H）一并载明。给 O/N 加 H 前、或某个 H 反复重定位时读此卡。
alerts: []
tools: [add_hydrogens, inspect_map, add_atoms_from_difference_map, run_shelxl, edit_atoms, write_outputs]
tags: [氢原子, OH, 羧基, 配位水, 诚实披露, 精修纪律]
source: 三役各自重新发现同一结论：r14b OH 拉锯 ~6 min（10:38-10:44 smtbx 崩溃→AFIX 147 转回碰撞→DFIX 不支持→删除）；r19 COOH ~6.5 min（O7/O8 双分支→SHELXL 拒回放自由 H→负 Uiso→删除）；r12 H3O 扭转 60 周期振荡→删除
confidence: high
created_by: mentor
---

## 判据（前置，别先拉锯再总结）

给 O/N 上的可旋转 H（羟基、羧基质子、配位水/骨架水氢）定向之前，先查
证据；出现**任两条同向**即判"数据不约束该 H 取向"：

1. omit 差图在化学合理扇区内最强峰 <~0.5 eÅ⁻³（inspect_map 亲验，勿
   直接信 add_hydrogens 的自动放置）；
2. AFIX 147/148 类扭转氢在相邻精修轮间来回翻转（>60° 摆动）或转回
   短接触（H···H <1.9 Å、H···X 撞 vdW）；
3. 该 H 精修出负 Uiso / NPD，或被内核强行各向异性化；
4. SHELXL 重精修后几何回到碰撞位（约束住的"解"其实是软件僵持）。

## 处置（一次到位）

- **删 H 坐标、保留化学计量**：H 计入化学式与 UNIT（SHELX 惯例允许
  未定位 H 只记账不建模），_refine_special_details 写明"X–H 氢未能由
  差值密度可靠定位，未包含坐标"；VALIDATION 列入 unresolved。
- 氢键网推断（受体距离 2.6-3.0 Å 的 O···O）可以写进讨论，但**不作为
  放 H 坐标的依据**。
- 确需测定取向：低温重收数据或中子，写进建议，不硬解。

## 密度确实支持时的正道

omit 峰 ≥~0.5 eÅ⁻³ 且位置化学合理：用差图 H（add_atoms_from_
difference_map 按峰加）+ 骑乘化或固定坐标，精修两轮验证 Uiso 为正、
无短接触、位置稳定，三条全过才算定住。

## 平台边界（绕不过，别撞）

- smtbx `refine` 不支持 H 上的 DFIX/DANG（返回 warning 并跳过），
  H 几何约束只能走 SHELXL 路线；
- `run_shelxl(adopt)` 的骑乘重放丢 H 时会**自动逐载体救援**（把该载体
  全部 H 按 SHELXL 模型原样恢复，summary 出 h_replay_rescued；SHELX
  作业保留 AFIX，进程内 refine 视其为自由原子）；仅当 h_replay_lost
  仍出现（快照里也找不到）才是真丢失，**带该警告不交付**；
- `edit_atoms` 搬 H 后骑乘元数据可能失效（历史上曾致 scitbx 断言崩溃）
  ，搬 H 后必跑一轮 refine/add_hydrogens 重建再继续。
