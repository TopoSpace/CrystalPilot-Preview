---
name: big-structure-refinement-pacing
description: 大结构（P1/低对称、>1500 参数、>20k 反射、含掩膜）单轮精修极贵：refine/optimize_weights 单次调用可跑很多分钟仍属正常，等待≠失败。策略：2-3 周期增量调用代替一次大周期数；掩膜节点每次 build 都重算 solvent_mask（FFT 是主开销）；调用无错误输出时保持等待勿重复提交同名调用（节点树可核实是否已提交）。收尾用 run_shelxl 独立复核。
alerts: []
tools: [refine, optimize_weights, run_shelxl, solvent_mask, list_nodes]
tags: [性能, 大结构, P1, 周期, 增量精修, 等待]
source: r12-mofval CD-MOF 战役实测（P1 400 原子全各向异性 ~2000 参数 + 24k 反射 + 掩膜；agent 自发改 2-3 周期增量策略后单调用时长回到可预期范围）
confidence: high
created_by: mentor
---

# 大结构精修节奏

## 何时读这张卡

- 空间群 P1/P-1 且原子数 ≳300，或参数数 ≳1500、独立反射 ≳20k；
- 正在等待 refine / optimize_weights 且时间远超小结构经验值；
- 模型带 solvent mask（f_mask 活跃）。

## 判断与策略

1. **等待≠失败**。受管精修调用无错误文本时保持等待，不要重复提交同名
   调用（重复提交会排队并撕裂节点审计）。用 `list_nodes` 核实上一次调用
   是否已提交节点，再决定重试。
   **心跳会告诉你在算什么**：refine 每 ~20s 发"computing, Ns elapsed
   (inside the tool, not waiting on approval)"，optimize_weights 逐轮
   报 a/b/GooF，export_twin_hklf5 报 1/4-4/4 阶段，收到心跳=正在计算，
   **不是审批排队**（r12 曾两次误归因）；心跳停了才值得起疑。
   optimize_weights 的 n_rounds 计入 bisection 兜底（可超过 max_rounds，
   summary 的 phases 字段给拆分），不是 bug。
2. **增量周期**。大结构上用 2-3 周期一次的增量调用取代一次 8+ 周期：
   单调用时长可预期、每步落节点、失败损失小。收敛判据看 shift/su 与
   R1 变化趋势，不看单次周期数。
3. **掩膜是主开销**。f_mask 活跃时每次结构因子构建都伴随溶剂掩膜 FFT
   重算，掩膜参数不变时避免无谓的 mask 刷新；改模后确需刷新时接受该
   成本并在一次调用里多做点事。
4. **权重优化放最后**。optimize_weights 在大结构上同样昂贵且不改化学；
   等模型稳定后做一次即可，结果以独立 run_shelxl 的 GooF/wR2 复核为准。
