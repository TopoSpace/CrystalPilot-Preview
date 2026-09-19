# 最终 CIF 验证说明

验证对象：`final.cif`  
验证程序：本地 PLATON/checkCIF  
最终任务：`job_20260829_044119`  
警报计数：A=3，B=3，C=3，G=16

结构模型的独立 CrystalPilot 验证为 100/100、无化学/连通性/ADP 警报；最终 SHELXL 指标为 R1=0.0426、wR2=0.1206、GooF=0.986，残余密度 `+0.497/-0.358 e Å⁻³`。以下 A/B/C 项均来自实验元数据或验证环境，而不是未解决的结构化学错误。

### A 197 Missing _cell_measurement_temperature Datum .... Please Add

- 含义：缺少用于晶胞测量的温度。
- 本结构中的原因：原始 CBF、DIALS 实验文件和用户提供的合成/采集先验均未记录温度。
- 已做的检查/尝试：检查了项目 experiment 元数据及帧头；SHELXL 自动假设的 293(2) K 不是真实观测，已从最终 CIF 改回 `?`。
- 影响评估：不影响空间群、坐标或 R 因子，但会影响热参数比较及期刊实验表完整性。只有 Diamond I19 日志或实验记录能消除此项。

### A 198 Missing _diffrn_ambient_temperature Datum .... Please Add

- 含义：缺少衍射采集环境温度。
- 本结构中的原因：与 A197 相同；采集温度没有保存在当前可用记录中。
- 已做的检查/尝试：没有用常见的 100 K、293 K 或文件名线索代替测量值；CIF 明确保留未知值。
- 影响评估：结构模型仍可信，但提交数据库/期刊前应从线站元数据补回真实温度。不能用计算消除此项。

### A 699 Missing _exptl_crystal_description Value .... Please Do !

- 含义：缺少晶体外观/形貌描述。
- 本结构中的原因：没有样品照片、安装记录或实验日志描述针状、块状、片状等形貌。
- 已做的检查/尝试：核对 context 与 CBF 元数据；探测器图像不能可靠反推晶体形貌，因此未编造描述。
- 影响评估：不影响衍射模型，但属于期刊要求的实验元数据。需实验人员根据安装记录补充。

### B 051 Mu(calc) and Mu(CIF) Ratio Differs from 1.0 by 9.58 %

- 含义：PLATON 自行计算的线性吸收系数与 CIF 中 `μ=0.493 mm⁻¹` 相差 9.58%。
- 本结构中的原因：波长 0.68890 Å 为非标准同步辐射波长；CIF/SHELXL 与 PLATON 的 Brennan–Cowan 插值表并不完全相同。同一检查同时给出 S 的 f′/f″ 表值差异（G984/G985），与此警报一致。
- 已做的检查/尝试：复核了化学式 C3H7NO2S、Z=4、晶胞、波长和原子散射类型；均正确，且未使用溶剂掩膜。没有为了消除警报而调节 μ。
- 影响评估：DIALS 多扫描吸收分量仅 0.9993–1.0011，实际方向相关校正极小；该表值差异不影响原子模型。投稿时可按期刊指定的统一同步辐射截面表重算 μ，以消除此项。

### B 196 No TEMP record and _measurement_temperature .NE. 293 Degree

- 含义：内嵌 SHELXL RES 没有 TEMP 卡，而 CIF 温度又不是 SHELXL 默认的 293 K。
- 本结构中的原因：真实温度未知。写入任意 TEMP 值都会把未知元数据伪装成测量值。
- 已做的检查/尝试：检查了帧头和项目实验块；明确删除自动生成的 293(2) K，同时保留氢原子的显式差值图定位和 DFIX 处理，避免温度默认值影响 HFIX 距离解释。
- 影响评估：这是 A197/A198 的伴随警报，不表示氢模型失效。获得真实采集温度后，在 CIF 和 SHELXL TEMP 卡中一致补入即可消除。

### B 995 Can not Recreate .fcf from Embedded .res & .hkl ! Check

- 含义：本次 PLATON 进程未能调用 SHELXL 从 CIF 内嵌 RES/HKL 重建 FCF。
- 本结构中的原因：该 checkCIF 作业的 `platon.out` 明确报告 “SHELXL20xy Type Executable Required”，即 PLATON 子环境找不到 SHELXL 可执行文件；本结构没有 `.fab` 或溶剂掩膜，知识库中关于掩膜的通用原因不适用。
- 已做的检查/尝试：CrystalPilot 已独立运行真实 SHELXL-2019/3；其 R1=0.0426、R1(all)=0.0470、wR2=0.1206、GooF=0.986，与最终 CIF 完全一致。`final.fcf` 已由该 SHELXL 作业生成并随交付提供；CIF 中 RES/HKL checksum 也通过。
- 影响评估：这是本地验证环境限制，不是结构因子不一致。装有 SHELXL20xx 的期刊/官方 checkCIF 环境应可复算；投稿前可在该环境再验证一次。

### C 053 Minimum Crystal Dimension Missing (or Error) ... Please Check

- 含义：缺少晶体最小尺寸。
- 本结构中的原因：样品安装/测量记录未提供三维晶体尺寸。
- 已做的检查/尝试：CBF 和 DIALS 文件不含可靠晶体尺寸；未用光斑尺寸或吸收系数反推。
- 影响评估：不影响当前结构解，但会限制吸收校正与实验描述的可审计性。需从安装记录补入。

### C 054 Medium Crystal Dimension Missing (or Error) ... Please Check

- 含义：缺少晶体中间尺寸。
- 本结构中的原因：同 C053。
- 已做的检查/尝试：同 C053；没有假定等轴或规则形状。
- 影响评估：同 C053，需实验记录才能消除。

### C 055 Maximum Crystal Dimension Missing (or Error) ... Please Check

- 含义：缺少晶体最大尺寸。
- 本结构中的原因：同 C053。
- 已做的检查/尝试：同 C053；DIALS 的束斑/探测器几何不能替代实测晶体长度。
- 影响评估：同 C053，需实验记录才能消除。

## G 级信息项说明

G002/G003/G172/G178/G188/G860 来自已完整披露的 7 条 X–H DFIX 和 1 条局部 S/H SIMU；G017/G720 来自粗解阶段保留的 C1–C4 标签，但 CIF 的原子类型符号和散射因子正确；G092/G984/G985 是 0.68890 Å 同步辐射非标准波长及插值表差异；G941 报告实际多重度 4.2；G965 表示最后一次 SHELXL 给出新的建议权重，但当前 GooF=0.986 且工作台权重优化已稳定。这些均不是额外 A/B/C 结构警报。
