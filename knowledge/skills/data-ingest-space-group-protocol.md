---
name: data-ingest-space-group-protocol
description: 数据入口三路线（帧/厂商产物/他人CIF）逐段质量判断与空间群决定规程：dials.symmetry 只在 Sohncke 群里选（P2₁/c 会被报成 P2₁），定群必须用消光表+E 统计（帧路线看 scale_and_export 的 space_group_screen 字段；厂商 hkl 路线用 screen_space_groups 工具，无原子会话即可），定群后帧路线用 scale_and_export space_group= 重缩放；estimate_resolution 客观截断纪律（厂商路线自动退化为 12 壳层合并统计表）；错群哨兵三征。import_frames/ingest_vendor_data/import_cif_model/create_start_model 之前、或粗解后指标诡异时读此卡。
alerts: []
tools: [import_frames, find_spots, index_frames, integrate_frames, scale_and_export, estimate_resolution, screen_space_groups, ncs_audit, create_start_model, ingest_vendor_data, import_cif_model, run_shelxt, solve_charge_flipping]
tags: [入口, 空间群, 定群, 分辨率截断, 帧管线, 厂商产物, 错群]
source: AGENTS v21 入口段全文下沉（r5-r12 战役实证累积：dials.symmetry Sohncke 盲区、W(CO)₆ Pcmn、TCNQ 完整度、p770 HKLF5、r11 crystal.ini 晶胞先验）；DIALS 文档
confidence: high
created_by: mentor
---

# 数据入口与空间群决定规程

## 三条入口路线

1. **原始衍射帧**：`import_frames → find_spots → index_frames →
   integrate_frames → scale_and_export → create_start_model`。每阶段返回
   关键统计（斑点数、晶胞与空间群证据、RMSD、CC½/Rmerge/完整度），逐段
   判断质量再前进，不要盲跑到底。索引失败时优先喂晶胞先验（厂商
   crystal.ini/.p4p 的晶胞 ingest 会自动挖）。
2. **厂商软件产物**（SAINT/TWINABS/XPREP/CrysAlisPro 的 .hkl/.p4p/.ins；
   很多真实任务只给产物不给帧）：`ingest_vendor_data(source_dir=…)` 冷启动
   ，验证 SHELX hkl、识别 HKLF5 孪晶批次文件、取晶胞/波长/吸收记录，无
   ins 时生成无原子起点。官方还原产物质量通常优于对陌生仪器自行还原；
   两者都有时先用产物，帧留作交叉验证。
3. **他人精修的 CIF**：`import_cif_model`（cif+hkl 或 cif+fcf/sf-CIF 自动
   转 HKLF4；温度/晶体尺寸/吸收校正自动搬进 context）。骑乘氢约束不会
   继承，要精修先 add_hydrogens 重建。

## 分辨率诚实

缩放后跑 `estimate_resolution`：很多实验室数据衍射不到探测器边缘，按
CC½ 壳层曲线（辅 Mn(I/σ)≈2 双判据）判定真实分辨率。若建议 d_min 明显
粗于当前极限，用 `scale_and_export resolution=…` 重截并对比合并统计；
保留全分辨率导出作对照。截与不截都把依据写进报告，绝不许"试到 R 最低"
式截断。

## 空间群决定（核心规程）

- **dials.symmetry 的建议不可直接采纳**：它只在 Sohncke（手性）群里选，
  滑移面/反演心永远不会出现（P2₁/c 会被报成 P2₁，Pnma 报成 P2₁2₁2₁）。
- 定群依据 = 消光筛表（absence_evidence=**absent** 且解释消光数最多的
  候选）+ E 统计（|E²−1|≈0.97 中心对称 / ≈0.74 非心）。筛表是三态的：
  absent = 消光类显著弱于该群保留的反射；**undecidable = 两类分不开**，
  弱数据下的常态，**不是支持**（pa2 hex：整套数据 ⟨I/σ⟩ 0.4，七个 R 群
  "consistent"排最前，agent 声明 R-3，2/3 观测被当消光丢掉，R1 0.14 在
  错群里"看起来很好"）；violated = 有强反射。心化格子 undecidable 时只能
  靠原始格候选的求解试验裁决，change_space_group 会审计并拒绝无证据的
  心化（accept_absences=true 需写明独立证据）；螺旋/滑移 undecidable 只
  警告，按 Marsh 纪律以求解试错定夺并在报告说明。低对称群 Rint 必然更低
  ，那不是证据。帧路线看 scale_and_export
  返回的 `space_group_screen` 字段；厂商 hkl 路线跑 `screen_space_groups`
  工具（同一内核，无原子会话即可用；默认按晶格度规取劳厄类并披露，
  度规可高于真对称，榜单是证据不是判决）。**劳厄类拿不准时一次调
  `screen_space_groups(laue_group='all', merge_stats=true)`**：每个与度规
  相容的劳厄类各给一行 Rint/唯一数/完整度，候选表按类合并，不要按类
  逐个调用，更不要用 change_space_group 逐群声明来"看 Rint"（pa1 hex
  两个 run 各花 13 min 在这上面）。E 统计、N(z)、奇偶类强度（赝平移/
  超胞/中心格）、Friedel 差、Wilson 一律 `reflection_statistics`，
  不要自写 cctbx 脚本（pa1 七个 run 自写，12 次崩溃）。定群后：帧路线
  `scale_and_export(space_group=…)` 重缩放；厂商 hkl 路线在无原子会话
  直接 `change_space_group(space_group=…)` **声明**已决群（数据重合并、
  求解器照此出卡、start 模型重写跨重启存续）。
- **弃心红线（r16 实弹血案）**：孪晶叠加会把 |E²−1| 压向非心值，
  孪晶嫌疑数据"读起来非心"**绝不构成弃掉反演心的依据**；且 P1/P-1
  同属 Laue 类 −1，Rint 也分不出。心/非心之争一律**试错裁决**：先解
  先修中心对称候选（Marsh 纪律），只有它明确失败才转非心群。已在
  P1 解出的模型必跑 `check_symmetry`，其重原子锚点搜索在轻原子
  全错时仍能找回反演心（HEAVY-SUBSTRUCTURE 判语=低对称逃逸征）。
  模型里有"两个独立分子"时再跑 `ncs_audit`：强匹配+**有理**算符=
  漏掉的晶体学算符（r17 终态实测 0.98 匹配率、反演心正落 (½,½,¾)，
  即复合超胞折叠算符；r16 的 P1 双分子也是它一查便知）。
  P1 里 Z′ 翻倍、参数翻倍，噪声数据撑不起，"退到 P1 求稳"方向
  是反的：P1 是 Marsh 更正的头号来源。
- 定下后**必须 `scale_and_export space_group="…"` 重跑缩放**（dials.reindex
  落群后缩放，等价类完整→离群剔除正确；返回的合并统计即该群的数据侧
  裁决），再 `create_start_model`（自动继承新群）。不要手写脚本改文件。
- σ≤0/非有限行在 dials.hkl→crystal.hkl 交接时自动剔除（hkl_rows_dropped），
  无需手工清洗。

## 求解路线选择（冷启动）

小中型结构先试 `solve_charge_flipping`（可审计可控，接 interpret_peaks
按先验指认元素）；失败或大胞/重轻混合直接 `run_shelxt`（其空间群判定是
证据要报告）。SHELXT 会自行重拟晶胞：轻微漂移（零点几个百分点）是
正常精化；漂移大到改变 Niggli 特征或与指标化晶胞对不上，通常意味着
它解进了另一套格子描述（约化 setting 翻转、超胞/亚胞），此时不要
直接采纳，先对照两套晶胞的度规关系查明它动了什么，再决定跟谁走。
失败升级阶梯读 [[framework-solve-ladder]]。两条路线的尝试与选择理由
写进报告。

## 错群哨兵（粗解后警惕，见一个先查群再修模）

1. ASU 原子数×Z 与组成先验对不上（对称拷贝被当独立原子）；
2. optimize_weights 收敛到异常大的 b；
3. run_shelxl 与内核 R1 剧烈分歧。
