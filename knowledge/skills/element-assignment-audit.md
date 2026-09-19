---
name: element-assignment-audit
description: C/N/O 元素指认的证据判读规程：Ueq-邻居比方向、typed-N/O 受体环境哨兵（苯误判吡啶）、键长相容对照、汇证优先级与诚实披露模板。audit_element_assignment 输出的判读卡；盲测/无合成先验场景交付前必读。
alerts: [PLAT241, PLAT242, PLAT243, PLAT244]
tools: [audit_element_assignment, edit_atoms, get_geometry, inspect_model, write_outputs]
tags: [元素指认, C/N 区分, Ueq, 氢键受体, 诚实披露]
source: r13-p770 战役定级卡点（agent N10 vs 文献 N4：主配体 5 处 C→N + 晶格吡啶 vs 苯；晶胞/骨架全对而组成偏 1.5 rel）
confidence: high
created_by: mentor
---

# C/N/O 指认证据审计

**前提认识**：C/N/O 相差 1 个电子。R1>5%、完整度<95% 或孪晶数据上，
X 射线单独**常常不能定论** C vs N，文献作者靠合成知识定的，你没有就
如实披露。本卡教你把 audit_element_assignment 的三类证据汇成判断或
诚实的"无法定论"。

## 三类证据的方向性

1. **Ueq / 邻居均值比**（工具字段 u_eq_over_neighbours）：
   - **偏大（≥1.5）**= 该位点模型电子偏多 → 真实元素可能更**轻**
     （N→C 方向），但端基/甲基/晶格溶剂的转动热运动同样造成偏大，
     单邻居原子（terminal）此信号几乎无判别力。
   - **偏小（≤0.67）**= 模型电子偏少 → 真实元素可能更**重**（C→N/O）。
     这个方向受热运动干扰小，更可信。
   - 环内逐位对比比全局对比灵敏：六元环里唯一 Ueq 异常的位点才值得怀疑；
     整环都大（PLAT260）是溶剂松动，不是指认证据。
2. **typed-N/O 受体环境**（environment_note）：N/O 的孤对总要做事，
   接质子、配金属、或接受氢键。一个无 H、无配位、≤3.3 Å 内无受体接触的
   N/O 是化学闲置位点：
   - 晶格六元环上出现 → **苯被读成吡啶的经典征象**（r13 实例）；
   - 主配体上出现 → 检查是否该位点实为 CH（少了骑乘 H 会同时低估分子式 H 数）。
   - 反向不成立：有接触不证明是 N（C-H...π 等也给接触计数）。
3. **键长相容表**（bonds[].fits / if_swapped）：看**换判后是否更自洽**，
   不是看单键相容：芳香 C-C 1.36–1.44 与芳香 C-N 1.31–1.36 有重叠区，
   1.37 Å 两可；但若一个环的六条键在 C6 模型下全部落 1.37–1.40，
   而 C5N 模型要求其中两条压到 1.33-1.35，整环汇证偏向苯。
   环内键长方差小+均值 1.38–1.40 → C6；两条明显短 → 有杂原子。

## 判决优先级

合成/谱学信息 > 中子数据 > 三类证据**同向汇证** > 任何单一指标。
两类证据同向即可改判（edit_atoms reassign 后必须重精修验证 R1/Ueq
响应）；只有一类或互相矛盾 → **不改**，走披露。

## 诚实披露模板

无法定论时在 CIF `_refine_special_details` 写明（模板参见
refine-special-details-templates）：

> The assignment of atom X as N (vs C) is supported by [证据] but cannot
> be settled by X-ray data alone at this resolution/completeness;
> synthesis information was not available. The alternative assignment
> changes the formula to [替代式].

SUMMARY.md 的"模型判断"段同步写该两可性；unresolved 列表加一条。
**绝不**因为 checkCIF 的 PLAT241/242 想让 Ueq 平滑就改元素或加 ISOR
，警报解释权在化学，不在警报消除。

## 与其他工具的配合

- `get_geometry`（run_shelxl 后）给键长 esd - esd 大于两可区间宽度时
  键长证据自动降级。
- 差值图证据（difference-peak-reading 卡）：正峰压位点=太轻、负峰=太重，
  与 Ueq 方向互为印证。
- 占有率探针（谨慎）：branch 里把疑点原子设为 C 精修 vs 设为 N 精修，
  比较 R1/该位点 Ueq 是否更合理，这是合法竞争测试，但 ΔR1 通常 <0.001，
  只作辅助证据，不作单独判决。

## 金属键合的 C/N：先问它是什么（pa2 cage 三格教训，2026-09-03）

- **SHELXT 组成串（尤其占位的 "C H N O"）给出的 C/N 标签只是峰高启发，
  不是元素证据。** pa2 三格把六金属节点的 μ₃-O/OH 与羧酸 O 留成 C/N，
  交付里带着 10–13 条 M–C 2.1–2.6 Å、18 条 M–N 与 30 条 N–N "键"；一格
  把这些 M–C 塞进 add_hydrogens 的 exclude 了事，那不是处理。
- add_hydrogens 现在按同一审计逐原子判定并在 summary.decisions 表里
  逐行说明（label/element/n_heavy_neighbours/geometry/decision/n_h/kind/
  reason）：没有碳骨架的金属键合 "C/N" 自动 decision=skipped，reason 给出
  审计等级与候选身份（改判用 edit_atoms reassign，不必也不该 exclude）；
  η 环碳（Cp/芳环）自动按芳香 CH 加 H；审计认可的 σ M–C 按自身几何
  加 H（M–CH₂R 两个、羰基/氰基/芳基 ipso 零个）；孤立的金属键合 "C"
  （水/羟基 O 还是 M–CH₃ 几何分不清）不猜 H 数，确是甲基时用
  force_kind={"C7": "CH3"} 逐原子选入。先读 decisions 再动 exclude。
- 金属键合原子的身份由 **M–X 距离、有无碳骨架、Ueq、省略图电子数**
  决定：落在 M–O 距离内、没有碳骨架的 C/N 首先怀疑为该金属的常见给体
  （硬金属：μ-O/OH、羧酸 O、F⁻/Cl⁻；软金属：S、卤素、N），桥接 ≥2 金属
  的更是；三角碳上 1.2–1.3 Å 的端基原子是羧酸/硝酸 O；Ueq 比同金属其他
  轻邻居塌陷 = 应更重。真正的 M–C（羰基/氰基/炔基端基、σ-烷基/芳基、
  NHC）有自己的骨架特征，审计列为 plausible_metal_bonds 并计入 CN。
- **金属旁一圈 2.3–2.8 Å 的 C 先查 η 环**（validate_structure 的
  pi_ligand 按一个配体计 CN），不要当短接触、幽灵或"连接算法过宽"；
  环内的 N 标签几乎总是 Cp 碳。
- **N–N 1.2–1.8 Å 只在唑环/叠氮/N₂ 里成立**，其余按几何改判为 C–C/C–N；
  C–C 1.20–1.28 Å 非线性者一端是 O。
- 处置：validate_structure 的 metal_bonded_light_atom / suspect_nn_bond /
  suspect_cc_bond 警报出现时，用 edit_atoms reassign 改判 → 重精修 →
  核对 Ueq 与残差；audit_element_assignment 每行带 metal_bonded_verdict。
  金属 CN 不计 H；裁决警报（mark_adjudicated）的 subject 不分大小写
  （SHELXL adopt 会把标签改成大写）。

## 重原子身份（金属/卤素）：先证据，后竞争（pa1 批测教训，2026-09-02）

- 先 `audit_heavy_sites`：每个 Z≥11 位点给 Ueq-配位比、CN 与 M–X 键长
  对候选窗口的相容性、位点残差符号、簇模式（Zr₆ 节点/Cu₂ 桨轮/M₃O）、
  λ 处 f'/f'' 与吸收边旗标，以及 **R-vs-Z 就绪判定**。工具只给证据。
- **R 阶梯只在就绪模型上做**：主体完整、溶剂已掩膜或建模、H 已放、WGHT
  已采纳。不完整/无掩膜模型上 R 随 Z 单调下降（pa1 cage-l0-r1：Cr→Br
  一路降到 0.247），相邻 Z 的 ΔR1<0.005 测到的是模型缺陷不是元素。
  竞争用 `element_scan(site, elements)` 一次跑完、同一引擎同一掩膜权重。
- **吸收边**：λ 靠近某元素吸收边时该元素看起来轻一档，0.68883 Å 正是
  Zr K 边（f'≈−9 e，Zr 的有效电子数≈31≈Zn）。候选集必须含边上元素；边上
  位点被判成轻元素时中心残差是**负**的，"正残差=偏轻"的方向判据失效；
  标度因子会吸收绝大部分 Z 失配，位点残差只看符号不看电子数。
- **采集建议（写给下一次实验）**：0.68883 Å = 18.000 keV 正是 Zr K 边
  （17.998 keV），含 Zr 样品把能量设在边下方几百 eV（0.70–0.72 Å），
  否则 f' 落在最陡的坡上、Zr 荧光抬高背景、吸收跳变；有意要反常信号
  就做荧光扫描测边并用 Kramers–Kronig 取真实 f'/f''。已在边上采的数据：
  元素身份看几何与反常差异图（只有 Zr 位点在 f'' 图里亮），不看 R。
- **两引擎的 f'/f''**：进程内 `refine` 每轮按数据波长设 Sasaki 项；
  `run_shelxl` 自 2026-09-02 起在非 Cu/Mo/Ag Kα 波长下自动写
  `DISP $El f' f'' mu`（同一 Sasaki 表）。job.ins 里出现 "REM DISP not
  written" 就是波长未知，SHELXL 会**静默沿用 Mo Kα 表**（不是零，真
  二进制实测），那份作业的 R 不能用于元素比较。两个引擎的 R 值永不互比。
- 重位点先由化学定候选（CN、M–X 窗口、簇拓扑、合成投料），Ueq/残差
  方向只作旁证；改判后必须重精修验证 CN/几何/残差，并在报告披露 R 阶梯
  是最后一步而不是依据。pa1 hex-l1-r1 把 NU-1000 的 Zr 全部标成 Zn
  （R1 0.0817 vs 0.0904），validate_structure 的 "Zn CN=8 outside [4,6]"
  两次被 R 值否决，这就是本节要防的错误。
