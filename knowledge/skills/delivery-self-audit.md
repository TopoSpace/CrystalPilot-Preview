---
name: delivery-self-audit
description: 交付前 CIF/RES/会话三方自洽审计，原子数、PART 内 H 数、FVAR 值必须一致
tools: [write_outputs, run_shelxl, run_checkcif]
tags: [交付纪律, 守恒审计, 无序]
source: practice-770 campaign rounds 4-7 (task_20260830_151405)
confidence: high
created_by: agent
updated: 2026-09-01
---

## 规则

交付（write_outputs + run_checkcif）之前，做三方一致性核对：

1. **原子数守恒链**：会话模型原子数 == final.res 原子行数 == final.cif
   _atom_site 行数。任何一步骤（尤其 run_shelxl adopt、checkout、
   change_space_group 重建）之后原子数变化都必须能解释；无法解释的
   减少 = 有原子被静默丢弃，停下排查，不带病交付。
2. **PART 内 H 数**：无序模型里进 PART 块的 H 数应等于按载体逐一折算
   的期望值（每个无序碳载体的 H 跟随其 PART）。final.res 里 grep PART
   区块核对；add_hydrogens summary 的 n_h_in_disorder_parts 是引擎侧
   参考值。
3. **FVAR 一致**：final.res 的 FVAR 行、final.cif 的占有率列、
   run_shelxl summary 的 disorder_occupancies 三处数值一致（换算
   minor = 1 - FVAR_k）。
4. **义务清单清偿**（2026-08-31 起 write_outputs 自动返回）：summary
   里出现 `mask_obligations`（掩膜交付：moiety 客体估计、VALIDATION
   电子数化学指认、squeeze 记录自检）或 `disorder_obligations`（每处
   PART 无序的精修描述，read_skill refine-special-details-templates）
   时，逐条完成后再结束，义务未清就收工等于把审稿必问题留给用户。
5. **归档只取 workbench 本地副本，绝不回读 staging/**：交付附件
   （hkl/日志/state.json）一律从项目目录内已有副本复制。r19 实证：
   从只读 staging 目录 Copy-Item 挂起 2×15 分钟（占战役 57%），改取
   workbench 副本秒成。SHELL 复制类命令给出 30-60s 超时预期，超时即
   换源而不是重试同路径。
6. **checkCIF 产物不手抄**（2026-09-01 起）：对 final.cif 跑
   run_checkcif 时，checkcif.json 与逐条脚手架 checkcif_alerts.md
   已自动写进交付目录，VALIDATION.md 的警报章直接在脚手架的
   explanation 槽上成文，别再自写转录脚本；修完重跑看 summary 的
   delta（new/resolved）核实警报确实消了。
7. **交付状态与定稿**（2026-09-02 起）：`write_outputs(status=)` 给交付
   一个机器可读状态，provisional（默认）/ diagnostic（诊断模型：否决的
   空间群、试探元素、无掩膜对照，不是结构主张）；final 只能由
   `finalize_delivery` 在 run_checkcif + SUMMARY.md/VALIDATION.md 之后
   授予，A 级警报与 unresolved 须修复或逐条 waive 带理由（记入
   REPORT.json），diagnostic 不可升级。write_outputs 返回的 key_facts /
   cif_missing_metadata（每个 `?` 字段对应的警报码与 set_experiment 键）
   直接用于 SUMMARY/VALIDATION，不要再用 shell 回读 REPORT.json；掩膜
   交付自动带 final.fab（final.res 含 ABIN），不要手拷 job.fab。pa1：
   cage-l2-r1 SUMMARY 否决了 I2/a 而 final.cif 仍是 I2/a、hex-l2-r3
   缺 SUMMARY/VALIDATION 照样放行，状态字段就是为这两种情况设的。

8. **标签必须能读成其元素**（2026-09-03 起 write_outputs 把关）：读者、
   checkCIF 和评分器都从标签读元素，N62 却是 O、C1 却是 Zr、残留的 Q
   峰标签，都是禁交付项；工具给出 rename_atoms(mode='map') /
   edit_atoms reassign 的一步修法，确有理由的非常规标签用
   accept_label_mismatch=true + reason 记录在案。"无匹配 SHELXL 作业"
   的拒绝会写明三条件（R1、原子/H/FVAR、Z）和最新作业差在哪一条；只改
   元数据（set_experiment）不必重跑作业。
9. **SUMMARY 必列会话最佳节点及未采用理由**：write_outputs 返回
   better_nodes 时逐个说明（掩膜被撤、诊断分支、化学不成立……），评分器按
   同一张表核对；说不出理由就该交付那个节点。
10. **引用工具诊断时写明"这是工具输出而非核实结论"**：validate_structure /
    audit_* 的警报是证据不是判决；SUMMARY 里凡引用，标明是否已核实、
    核实方法是什么。
11. **unresolved 里禁止写无日志依据的物种名**：写"孔道内可能有 DMF"必须能
    指向电子数、差图峰形或投料记录；没有依据就写"未指认的弥散密度 N e"。

## 出处

练习770 战役（CCDC 2484845 对照）第四轮：SHELXL job 180 原子、活动节点
只有 174 - 6 个 H 在 adopt 写回链上静默丢失；第六轮同类丢失只剩 1 个
（H16B）也被此纪律拦下。两次都是靠原子数守恒核对发现的，工具摘要
当时并不报警（引擎缺陷 #13/#14 后已加 h_replay_lost 显式报警，但
交付方自查仍是最后防线）。
