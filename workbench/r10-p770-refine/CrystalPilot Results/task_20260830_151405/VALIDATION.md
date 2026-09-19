# 第七轮 checkCIF 逐条说明

最终本地PLATON检查结果为7A/2B/14C。以下逐条对应最终 `final.cif`；G级信息未列为阻断项，但原始结果保存在 `checkcif.json` 与 `checkcif.chk`。

### A PLAT029 `_diffrn_measured_fraction_theta_full value Low . 0.907 Why?`

- 含义：标准分辨率范围内的数据完整度偏低。
- 本结构中的原因：CIF给出的theta_full完整度为90.7%，原始合并数据整体完整度仅74.1%；高角覆盖受数据采集几何/原始还原范围限制。
- 已做的检查/尝试：保留全部可用数据，未为降低R值做人为分辨率截断。
- 影响评估：降低低占有率无序组分的独立约束能力；彻底消除需要重新采集覆盖更完整的数据。

### A PLAT080 `Maximum Shift/Error ............................ 1.95 Why ?`

- 含义：末周期最大参数位移相对标准不确定度仍偏大，数值精修未完全收敛。
- 本结构中的原因：四组低占有率无序的坐标、ADP与FVAR高度相关，主要不稳定来自腈侧叔丁基占有率。
- 已做的检查/尝试：依次执行20、50及100周期SHELXL；R1稳定在0.0647–0.0648，但最大shift/esd仍为1.947，继续循环没有带来实质R值改善。
- 影响评估：占有率精确值应谨慎引用；主骨架、元素指认和连接关系不因此改变。投稿时须披露，进一步解决需更完整数据或重新参数化无序模型。

### A PLAT183 `Missing _cell_measurement_reflns_used Value .... Please Do !`

- 含义：缺少晶胞测定所用反射数。
- 本结构中的原因：现有厂商还原产物/项目上下文未提供该实验字段。
- 已做的检查/尝试：检查项目实验元数据；没有可追溯数值，因此未编造。
- 影响评估：属于实验报告完整性问题，不改变当前结构模型；需从原始SAINT/APEX处理报告补录。

### A PLAT184 `Missing _cell_measurement_theta_min Value ...... Please Do !`

- 含义：缺少晶胞测定反射的最小theta。
- 本结构中的原因：原始实验元数据缺失。
- 已做的检查/尝试：未用衍射极限或后验范围冒充晶胞测定范围。
- 影响评估：不改变模型，但投稿前应从原始处理报告补充。

### A PLAT185 `Missing _cell_measurement_theta_max Value ...... Please Do !`

- 含义：缺少晶胞测定反射的最大theta。
- 本结构中的原因：同PLAT184。
- 已做的检查/尝试：保持未知值。
- 影响评估：实验元数据缺口；需原始处理报告才能消除。

### A PLAT699 `Missing _exptl_crystal_description Value ....... Please Do !`

- 含义：缺少晶体形貌描述。
- 本结构中的原因：用户未提供晶体颜色和外形。
- 已做的检查/尝试：项目上下文仅有仪器与波长，不能从衍射文件可靠反推出外观。
- 影响评估：不影响结构解，但投稿表格不完整；需实验记录补充。

### A PLAT881 `No Datum for _diffrn_reflns_av_R_equivalents ... Please Do !`

- 含义：缺少等价反射合并R值。
- 本结构中的原因：当前 `crystal.hkl` 是已合并的独立反射集合，报告的Rint=0仅表示没有重复观测可重算，不能作为真实实验Rint。
- 已做的检查/尝试：没有把0.000写成有物理意义的Rint。
- 影响评估：限制数据质量评价；需原始未合并积分文件或厂商还原报告补充。

### B PLAT025 `Hmin..Lmax Data Incomplete or Missing .......... Please Check`

- 含义：CIF缺少或不能完整重建HKL索引上下限。
- 本结构中的原因：输入为已处理HKL，部分数据采集范围元数据没有传入CIF装配上下文。
- 已做的检查/尝试：最终FCF包含实际用于精修的反射；没有凭空填写索引范围。
- 影响评估：主要影响CIF实验段完整性；提交时应同时提供 `final.fcf`，并从原始处理报告补字段。

### B PLAT995 `Can not Recreate .fcf from Embedded .res & .hkl ! Check`

- 含义：PLATON不能从CIF内嵌RES/HKL完全复算FCF。
- 本结构中的原因：本结构未使用溶剂掩膜；更可能是当前装配器的内嵌HKL/RES表示与独立SHELXL作业不完全可复算，而不是FAB缺失。
- 已做的检查/尝试：独立SHELXL真实作业已成功，`final.fcf`已由该作业直接输出；CIF/RES原子数、H、PART与FVAR另行逐项审计一致。
- 影响评估：属于交付封装兼容性警报；不否定独立FCF，但投稿必须随附 `final.fcf`，最好由原始SHELXL归档重新打包以消除。

### C PLAT052 `Info on Absorption Correction Method Not Given Please Do !`

- 含义：未说明吸收校正方法。
- 本结构中的原因：现有项目上下文未给出TWINABS/SADABS等具体方法和透射范围。
- 已做的检查/尝试：没有根据仪器型号猜测吸收校正软件。
- 影响评估：La/Ni结构对吸收处理较敏感；应从还原记录补充，不能靠模型精修消除。

### C PLAT053 `Minimum Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体最小尺寸。
- 本结构中的原因：未提供晶体尺寸。
- 已做的检查/尝试：保持未知。
- 影响评估：实验元数据缺失；需实验记录补充。

### C PLAT054 `Medium Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体中间尺寸。
- 本结构中的原因：同PLAT053。
- 已做的检查/尝试：保持未知。
- 影响评估：需实验记录补充。

### C PLAT055 `Maximum Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体最大尺寸。
- 本结构中的原因：同PLAT053。
- 已做的检查/尝试：保持未知。
- 影响评估：需实验记录补充。

### C PLAT234 `Large Hirshfeld Difference C11--C38B . 0.19 Ang.`

- 含义：C11–C38B键两端沿键方向的ADP差异偏大。
- 本结构中的原因：C38B属于占有率约0.222的N3侧叔丁基次取向，坐标和ADP受弱密度约束。
- 已做的检查/尝试：该组已用同类键SADI及局部SIMU；C11–C38B=1.529(17) Å，化学键长合理。未额外添加DELU以免过约束低占有率组分。
- 影响评估：影响次取向ADP精度，不改变主骨架连接；可在更完整数据下重新评估。

### C PLAT241 `High 'MainMol' Ueq as Compared to Neighbors of N4 Check`

- 含义：N4的Ueq相对邻原子偏高。
- 本结构中的原因：N4是线性腈端并与Ni配位，局部振动/残余无序使其ADP高于C3。
- 已做的检查/尝试：Ni–N4=1.872(7)、N4–C3=1.166(8) Å，均强烈支持N4元素与连接；未按Ueq单一指标改元素。
- 影响评估：提示局域ADP模型不完美，但N4指认可靠。

### C PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of C3 Check`

- 含义：C3的Ueq相对邻原子偏低。
- 本结构中的原因：C3是腈碳，N4–C3短键和近线性几何使其位移受限；相邻N4较活跃放大对比。
- 已做的检查/尝试：N4–C3=1.166(8)、C3–C27=1.455(8) Å；加氢分类也按174°线性sp碳正确跳过C3。
- 影响评估：不支持C3改判为更重元素；与N4的局域ADP差异应披露。

### C PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of C11 Check`

- 含义：C11的Ueq相对其邻近无序原子偏低。
- 本结构中的原因：C11是叔丁基中心的全占有率锚点，邻接两套低占有率甲基取向，因此天然比末端无序原子稳定。
- 已做的检查/尝试：C11到六个备位的键长为1.516–1.549 Å，并用SADI/SIMU保持两取向可比。
- 影响评估：属于已建模无序造成的预期对比，不是元素误判证据。

### C PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of C27 Check`

- 含义：C27的Ueq相对邻近无序甲基偏低。
- 本结构中的原因：C27为腈侧叔丁基全占有率中心，邻接两套部分占有率末端碳。
- 已做的检查/尝试：C27–C键为1.496–1.538 Å；该组已有SADI和SIMU，未为消警报改变元素。
- 影响评估：主要反映无序层级，不影响连接关系。

### C PLAT250 `Large U3/U1 Ratio for <U(i,j)> Tensor(Resd 2) 2.2 Note`

- 含义：残基2的平均ADP张量各向异性偏大。
- 本结构中的原因：该残基为部分占有率无序片段，且整体数据完整度74.1%。
- 已做的检查/尝试：各向异性精修并使用有化学依据的局部SIMU；无非正定ADP报告。
- 影响评估：降低次组分位移参数精度，未显示需要删除真实密度支持的原子。

### C PLAT250 `Large U3/U1 Ratio for <U(i,j)> Tensor(Resd 3) 2.1 Note`

- 含义：残基3存在类似整体ADP各向异性。
- 本结构中的原因：低占有率无序与数据覆盖不足共同造成。
- 已做的检查/尝试：同PLAT250残基2，并核对相关键长合理。
- 影响评估：局部精度限制，不改变主分子组成。

### C PLAT260 `Large Average Ueq of Residue Including C28 0.116 Check`

- 含义：含C28的晶格苯组分平均Ueq偏大。
- 本结构中的原因：晶格苯是双取向、弱约束的晶格客体，主取向占有率约0.714。
- 已做的检查/尝试：两取向均以DFIX、FLAT和SIMU稳定；C28–C键实测1.372–1.373 Å。
- 影响评估：符合动态/静态无序客体特征；不应为降低Ueq而删除晶格苯。

### C PLAT260 `Large Average Ueq of Residue Including C28B 0.115 Check`

- 含义：晶格苯次取向平均Ueq同样偏大。
- 本结构中的原因：C28B组分占有率约0.286，密度更弱。
- 已做的检查/尝试：C28B–C40B=1.380(10)、C28B–C43B=1.393(10) Å，几何与芳环模型一致。
- 影响评估：次取向ADP定量精度有限，但存在性与几何可辩护。

### C PLAT342 `Low Bond Precision on C-C Bonds ............... 0.01088 Ang.`

- 含义：平均C–C键长精度约0.0109 Å，低于高质量小分子结构常见水平。
- 本结构中的原因：整体完整度74.1%、四组无序及大量相关参数共同放大esd。
- 已做的检查/尝试：保留高角数据，采用最小化的SADI/DFIX/FLAT/SIMU集合并完成各向异性精修。
- 影响评估：限制细微构象比较和占有率精度，但主要成键拓扑、组成和金属配位结论仍可靠；更高精度需重新测量。
