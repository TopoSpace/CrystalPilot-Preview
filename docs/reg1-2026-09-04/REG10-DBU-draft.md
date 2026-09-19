# reg10-dbu：第二轮 R5 端到端一格（复跑，草稿）

**实验设计**：与 reg9-dbu 完全相同的一格（orgdis_dbu，COD 2241572，B/full 臂，
模板 v36，gpt-5.6-sol @ xhigh，4 核，同一份数据），只多了 a311653 的修复
（numpy + scipy 在 anyio 循环之前导入，cctbx 系在主线程预热）。要回答 reg9
没答上的三问：**`analyze_packing` 是否在预算内返回并被读懂；HTAB 卡是否进
`final.cif`；对 reg7 / reg9 有无回归。**

**结论先行**：三问全部为"是"。`analyze_packing` 两次调用各 1.4 s 返回；agent
从它的 HTAB 卡里取出 `HTAB N2 O1`，之后每一次 `run_shelxl` 都带着
`extra_cards=["HTAB N2 O1"]`，交付的 `final.cif` 里有一条带 SHELXL esd 的
`_geom_hbond_` 行；评级 **publication**，R1 0.0463（参考 0.0447，Δ 0.0016），
组成与参考逐元素相同。R5 的一格端到端到此完成。

所有数字只来自 `workdir/campaigns/reg10-dbu/state.json`、
`dbu-full-r1/grade.json`、`verdict.json` 与交付目录的 `transcript.jsonl` /
`final.cif`；缺的字段打 ` - `。

## 1. 结果总表

| 晶体 | 臂 | 等级 | R1(agent) | R1(ref) | ΔR1 | 空间群一致 | 组成 | 诚实门 | 最佳节点是否交付 | 墙钟 | tokens in/out | 工具调用 | 未返回 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dbu | B/full v36 + a311653 | **publication** | 0.0463 | 0.0447 | +0.0016 | 是（P 1 21/n 1） | C16H20N4O6 = 参考 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF 解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:4 条 | 是（最佳可比 n0050 0.0441，交付 0.0463，Δ 0.0022 < 0.01；三个更低的节点参数数 >1.5×，不可比） | 28.9 min | 18,518,584 / 54,261 | 150 完成 | 0 |

checkCIF A×7 B×2 C×8：A 级 6 条是元数据缺失（183/184/185/197/198/699，不计
分），1 条 881（预归并 HKLF4 无 R_equivalents）。骨架 `framework_reproduced`
28/28，rms 0.007 Å。

## 2. 同格三次对照（n=1 各一次，只报事实）

| | reg7-dbu（v34/35 前） | reg9-dbu（v36，未修 P0） | reg10-dbu（v36 + a311653） |
|---|---|---|---|
| 等级 | publication | acceptable | **publication** |
| R1 / ΔR1 | 0.0475 / +0.0028 | 0.0551 / +0.0104 | **0.0463 / +0.0016** |
| 组成 | — | C15N5（多判一个 N） | C16N4 = 参考 |
| checkCIF A/B/C | 7/2/8 | 7/5/9 | 7/2/8 |
| 墙钟 | 22.7 min | 58.1 min（35 min 在等） | 28.9 min |
| tokens in | 10.24 M | 16.28 M | 18.52 M |
| 工具调用 | 236 | 134 + 1 未返回 | 150，0 未返回 |
| analyze_packing | 不存在 | 卡死 | 2 次，1.45 / 1.41 s |
| `_geom_hbond_` 进 CIF | 否 | 否 | **是（1 行，带 esd）** |

reg10 比 reg7 多 6 分钟、多 8 M 输入 tokens，换来的是氢键表进了 CIF、R1 更接近
参考、组成完全一致；单次运行的差异不能分离出"哪一项改动带来了哪一点"，
只能说**没有回归**。

## 3. 三问逐条

### 3.1 `analyze_packing` 在预算内返回、被读懂

- 第 1 次（约第 100 次调用）：`blocks=["interactions","packing","topology"]`，
  `criteria="olex2"`，1450 ms 返回；分析产物首次构建的分块耗时
  （产物新字段 `timings_s`）：interactions 0.12 s、pores 0.65 s、guests 0.22 s、
  topology 0.42 s。第 2 次（收尾前复核）`["interactions","packing"]`，1414 ms。
- 读懂的证据：agent 收尾裁决里用了它，"DBUH⁺ 与 3,5-二硝基苯甲酸根的化学归属
  由键连、键长、ADP、差值密度和候选模型精修比较共同推断"，且 `unresolved`
  里不再有 reg9 的"未生成完整的堆积相互作用/HTAB 表"。

### 3.2 HTAB 卡进 `final.cif`

`analyze_packing` 返回的 HTAB 卡是 `HTAB N2 O1`（N–H···O，同一非对称单元内，
无需 EQIV）。之后 7 次 `run_shelxl` 全部带 `extra_cards=["HTAB N2 O1"]`
（每次 0.3–1.3 s 返回），`final.res` 里有 HTAB 卡，`final.cif` 第 507–516 行：

```
_geom_hbond_atom_site_label_D ... _geom_hbond_publ_flag
N2 H1 O1  0.89(2) 1.89(2) 2.778(2) 175.7(19) . yes
```

esd 来自 SHELXL 本身（D11 关闭的机制第一次在真实交付里走通）。与
`analyze_packing` 的测量值对照：产物里这条氢键 D···A 2.77 Å、H···A 1.85 Å、
∠ 177.7°（骑乘 H），SHELXL 精修后 H 为自由原子 0.89(2) Å，H···A 1.89(2)、
∠ 175.7(19)，差别正是 `h_source` 说明里写的"骑乘 H 的 H···A 偏短/偏长"那一类。

### 3.3 无回归

- 评级、R1、组成、A/B/C 计数都不差于 reg7；比 reg9 全面好转。
- 参数摘要行继续有效：150 次调用无参数试探重试、0 次未返回。
- reg8 四项里本格走到的：`ingest_vendor_data` 2 次（重复 hkl 检查路径）、
  `model_disorder` 6 次（分裂后骑乘 H 复制）。`view_structure` 无原子晶胞视图与
  候选"已试/已裁决"列表本格无触发条件。

## 4. 其他观察

- 评分器的"更低 R1 但不可比"规则起了作用：n0049 / n0054 / n0055 的 R1 0.042
  级是 480 / 453 个参数（交付 246）买来的，评分器按 >1.5× 参数数判为不可比，
  没有把"交付比树内最佳差"错记在 agent 头上。
- 未决披露 4 条全部是实验元数据与数据前史（温度/尺寸/仪器、预归并 HKL、无合
  成先验、P2₁/n 非 ITA 标准设置），与 reg7 同类，没有新增工具缺陷。
- 25 条 agent 消息（reg9 是 40 条，其中 12 条是"仍在等待"）。

## 5. 下一步

- R5 收尾：本草稿 + UI-EVIDENCE R5 节 + CAPABILITIES R5 行改"完成"，
  tag `r2-r5-done`。
- reg9 §4 的轻原子 C/N 判断（本格没有复现）留作能力边界记录，不在本轮处理。
