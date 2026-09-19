# COD 2229074 独立验证总结

## 结论

论文的 R1(I>2σ)=0.0526 可以从沉积 `ref.fcf` 的 **Fo²/Fc² 成对数据**精确重算；但不能从派生 `ref.hkl` 的 Fo²/σ 和终稿 CIF 原子表重新精修复现。最终保留沉积模型节点 n0000，不用无证据操作追逐发表值。

核心原因是非merohedral 孪晶的数据处理信息在 FCF→HKLF4 时不可逆丢失。FCF 有 10,410 行、按 P-1/Friedel 合并为 3,046 组；2,315 组的沉积 Fc² 在重复 hkl 内不恒定，最大组内跨度 418.58。HKLF4 只保存 h,k,l,Fo²,σ，既没有这些逐观测 Fc²，也没有 twin law、HKLF5 分量/batch 或域比例，因而 SHELXL 只能按单畴模型重算 Fc。

## 计算与分支

- `import_cif_model`：由 atom loop 导入 44 个原子，P-1，末端乙基 C15/C16 为 0.643/0.357 两位点无序。CIF 没有内嵌 `.res`。
- 原样 SHELXL：10,410 个输入观测合并为 3,046 个独立反射，R_int=0.0822；R1(gt)=0.0933，R1(all)=0.0976，wR2=0.2806，GooF=2.305。
- FCF 独立审计：由四舍五入后的 FCF 取 Fo²>2σ 得 9,258 行，R1=0.0525847；与论文 0.0526 一致。论文写 9,282 个强反射，24 条差异归因于沉积数值四舍五入/原始阈值判断。
- n0001 骑乘 H 重建只识别 9 个 H，因 A/B 位点重叠拒绝无序乙基 H；检查 R1=0.1010，模型不完整，否决。
- n0002 自由精修 10 周期 R1=0.0942，未改善且低占位无序 H 的坐标/Uiso 失稳，否决。
- `check_symmetry`：P-1 完整，无漏对称；`set_twin(suggest)`：无度量学孪晶律。后者不反驳论文的非merohedral 孪晶，反而说明必须从原始帧/分量索引恢复。
- 差值图 +0.49/−0.30 e Å⁻³，无缺失重原子证据；确定性结构验证无连通性/组成警报。

## 模型与 restraint

终稿 CIF 报告 218 parameters、25 restraints、氢原子 constrained；atom-loop 重建得到 302 parameters、0 restraints。参数差与 A/B 无序位点的 PART/FVAR、ADP 约束以及 AFIX 丢失相符，但 CIF 未给出具体卡片，无法唯一复原。

本次新增 restraint：**0 条**。理由是原 25 条 restraint 的类型、目标和作用原子均未披露；猜加 SADI/DELU/RIGU 会把先验冒充为数据。最终保留原始坐标、ADP、占位与化学式 C16H14N2O5，并在 CIF 中补录原 CIF 已知的晶胞 s.u./测定元数据及 A/B disorder group；仅删除了显式几何表中不可能同时存在的跨构象伪键/伪角/伪扭角。

## 最终质量与限制

- 选定节点：n0000（沉积原子模型）
- 独立 SHELXL-2019/3：R1(gt)=0.0933，R1(all)=0.0976，wR2=0.2806，GooF=2.305
- 差值密度：+0.49/−0.30 e Å⁻³
- 最终本地 checkCIF：1 A、1 B、13 C；逐条解释见 `VALIDATION.md`

剩余 A/B 不是可接受的发表终点：A 080 表明派生数据上的无约束重精修未收敛；B 995 表明 embedded res+hkl 无法再生沉积 FCF。严格复现需要原始帧或保留 domain/component batch 的 HKLF5、孪晶矩阵/域比例及原始 `.res/.ins`。
