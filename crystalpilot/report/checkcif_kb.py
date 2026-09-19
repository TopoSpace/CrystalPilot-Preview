"""Curated knowledge base for PLATON/checkCIF ALERT codes.

Used by the run_checkcif tool to annotate每条 alert with what it means, its
common causes, and the usual remedies, so the agent can produce an honest
per-alert explanation (含义 / 本结构中的原因 / 已做的检查 / 是否影响可信度)
instead of guessing. Entries cover the codes CrystalPilot workflows actually
hit plus the high-frequency ones from the IUCr catalogue; unknown codes fall
back to the PLATON message text.

Alert TYPE (the digit): 1 CIF construction/syntax, 2 structure/displacement,
3 data/refinement quality, 4 improvements/omissions, 5 informative.
Alert LEVEL: A serious, B potentially serious, C check, G general info.
"""
from __future__ import annotations

KB: dict[str, dict[str, str]] = {
    # ---- data items / CIF construction (type 1/4) -------------------------
    "010": {"meaning": "CIF 中没有可用的（内嵌）反射数据",
            "causes": "CIF 未内嵌 _refln 环也未随附 fcf",
            "remedy": "用 SHELXL ACTA 输出（内嵌反射数据）或随附 final.fcf"},
    "023": {"meaning": "数据分辨率过低 (sin θ/λ < 0.6)",
            "causes": "数据确实只收到低角；或 CIF 没带反射数据导致按 0 计算",
            "remedy": "如数据确实有限，说明采集条件（同步辐射短波长、弱衍射晶体）"},
    "029": {"meaning": "_diffrn_measured_fraction_theta_full 偏低",
            "causes": "数据完整度不足（常见于高角缺失或探测器几何）",
            "remedy": "报告真实完整度并解释（如低温机遮挡、快速衰减晶体）"},
    "032": {"meaning": "Flack 参数 s.u. 过大（无判定力）",
            "causes": "轻原子结构 + Mo 辐射反常信号弱；数据冗余度/质量不足",
            "remedy": "run_shelxl 已回读 Flack(Parsons)；su>0.3 时如实披露"
                      "\"绝对结构未可靠测定\"（轻原子属正常），勿硬标构型；"
                      "含较重原子时检查数据质量或改 Cu 辐射重测"},
    "033": {"meaning": "Flack 参数值异常（偏离 0）",
            "causes": "x≈1 构型反了；x≈0.5 外消旋/反演孪晶；中间值多为"
                      "数据/吸收问题",
            "remedy": "x≈1 → invert_structure 后重精修复查；x≈0.5 → "
                      "set_twin(law='inversion') 由 SHELXL 精修 BASF；"
                      "中间值先查吸收校正与数据质量"},
    "916": {"meaning": "Flack x 与 Hooft y 不一致",
            "causes": "两种估计器对弱反常信号敏感度不同，弱信号时分歧属"
                      "统计正常",
            "remedy": "一般无需处理；在 VALIDATION 中说明两者 su 与信号"
                      "强弱即可（有合理解释即可）"},
    "037": {"meaning": "未给出 _diffrn_reflns_theta_full 值",
            "causes": "CIF 缺项", "remedy": "补齐数据处理统计"},
    "050": {"meaning": "未给出吸收系数 mu",
            "causes": "CIF 缺 _exptl_absorpt_coefficient_mu",
            "remedy": "由组成与波长计算（SHELXL ACTA 会自动给出）"},
    "081": {"meaning": "未给出最大 shift/su",
            "causes": "CIF 缺 _refine_ls_shift/su_max",
            "remedy": "取自最终精修轮（SHELXL 自动给出）"},
    "089": {"meaning": "吸收校正信息不完整",
            "causes": "缺 T_min/T_max 或校正方法",
            "remedy": "补 experiment.absorption（multi-scan/SADABS 等 + T 范围）"},
    "125": {"meaning": "未给出 _space_group_name_Hall",
            "causes": "CIF 缺 Hall 记号", "remedy": "补 Hall 记号（可由软件生成）"},
    "141": {"meaning": "a 轴标准不确定度缺失或为 0",
            "causes": "ZERR 未带真实晶胞 esd（粗解/中间模型常见）",
            "remedy": "从原始 .ins 传递 ZERR esd，或由指标化软件提供"},
    "142": {"meaning": "b 轴标准不确定度缺失或为 0", "causes": "同 141",
            "remedy": "同 141"},
    "143": {"meaning": "c 轴标准不确定度缺失或为 0", "causes": "同 141",
            "remedy": "同 141"},
    "151": {"meaning": "晶胞体积未给出 s.u.",
            "causes": "晶胞 esd 全零，体积 esd 无法传播", "remedy": "同 141"},
    "183": {"meaning": "缺 _cell_measurement_reflns_used",
            "causes": "未记录晶胞测定用的反射数（来自指标化软件）",
            "remedy": "从数据处理软件（SAINT/CrysAlis/DIALS）提取，或如实留空并说明"},
    "184": {"meaning": "缺 _cell_measurement_theta_min",
            "causes": "同 183", "remedy": "同 183"},
    "185": {"meaning": "缺 _cell_measurement_theta_max",
            "causes": "同 183", "remedy": "同 183"},
    "196": {"meaning": "无 TEMP 记录且温度 ≠ 293 K",
            "causes": "CIF 温度与内嵌 .res 的 TEMP 卡不一致/缺失",
            "remedy": "在 .ins 写 TEMP 卡（CrystalPilot 从 experiment."
                      "temperature_K 自动写入）"},
    "197": {"meaning": "缺 _diffrn_ambient_temperature",
            "causes": "未记录采集温度", "remedy": "补 experiment.temperature_K"},
    "198": {"meaning": "缺 _cell_measurement_temperature",
            "causes": "同 197", "remedy": "同 197"},
    "699": {"meaning": "缺晶体外观描述 (_exptl_crystal_description)",
            "causes": "未记录晶体形貌", "remedy": "补 experiment.crystal"},
    "790": {"meaning": "CIF 中存在孤立原子（与任何原子不成键）",
            "causes": "孤立溶剂 O、被删剩的碎片、或掩膜前残留",
            "remedy": "确认孤立原子的化学身份（配位水/游离溶剂）并说明"},
    "808": {"meaning": "未能解析 SHELXL 风格权重方案",
            "causes": "CIF 缺 _refine_ls_weighting_details",
            "remedy": "由 SHELXL ACTA 输出自动携带"},
    "860": {"meaning": "SQUEEZE/掩膜处理信息缺失",
            "causes": "用了溶剂掩膜但 CIF 未写 _platon_squeeze_* 文档",
            "remedy": "CrystalPilot 装配器自动补 _platon_squeeze_details+void 环"},
    "990": {"meaning": "SQUEEZE 作业使用了过时的 .res/.hkl 输入风格",
            "causes": "ABIN/.fab 流程被 PLATON 识别为旧式",
            "remedy": "说明掩膜贡献经 .fab/ABIN 进入精修，属可接受工作流"},
    "995": {"meaning": "无法从内嵌 .res+.hkl 复算 .fcf",
            "causes": "①精修含 .fab（掩膜）贡献而 fab 未内嵌，PLATON 复算必然"
                      "不一致；②环境性：本地 PLATON 找不到 SHELXL 可执行时"
                      "同样报此警报（r10-p780 实证：platon.out 内有真因，"
                      "警报文本却伪装成 FCF 复算问题；r11_c 曾为此逆向工程"
                      "校验和 6 分钟零产出）",
            "remedy": "随附 final.fab 或说明掩膜工作流；怀疑环境性时读 "
                      "platon.out 一次定案，勿做校验和复算的兔子洞"},
    "780": {"meaning": "坐标未构成正确连接的原子集",
            "causes": "MOF 骨架跨对称元素，ASU 内片段彼此不相连属正常；也可能确有断键",
            "remedy": "用 grow/对称扩展确认骨架连通后说明；若确有断键需补原子"},
    # ---- structure / ADP (type 2) ----------------------------------------
    "213": {"meaning": "原子 ADP 长短轴比过大（prolate/oblate）",
            "causes": "末端配体（如端配水）真实热运动大；无序未拆分；元素判错",
            "remedy": "确认化学身份合理后如实说明；必要时拆分无序或加 ISOR/SIMU"},
    "220": {"meaning": "同种元素 Ueq 最大/最小比值大",
            "causes": "骨架 O 与端配/羟基 O 热运动差异；或有判错原子",
            "remedy": "核对每个高 U 原子的密度支持与配位环境后说明"},
    "222": {"meaning": "H 的 Ueq 与载体比值异常", "causes": "骑乘系数异常",
            "remedy": "检查 AFIX/骑乘设置（芳香 CH 应为 1.2×）"},
    "230": {"meaning": "Hirshfeld 刚性键检验差值大",
            "causes": "成键两原子 ADP 沿键方向差异大：元素判错或无序",
            "remedy": "复查元素归属；考虑 DELU/RIGU 或无序模型"},
    "241": {"meaning": "原子 Ueq 明显高于相邻原子",
            "causes": "占有率<1 的位置按全占精修；轻元素被判成重元素",
            "remedy": "检查该位点元素/占有率是否有密度依据"},
    "242": {"meaning": "原子 Ueq 明显低于相邻原子",
            "causes": "重元素被判成轻元素；或该位点确为更重原子",
            "remedy": "同 241，反向核查"},
    "250": {"meaning": "平均 ADP 张量 U3/U1 比大（整体各向异性强）",
            "causes": "层状/链状晶体真实热振动各向异性；数据各向异性截断",
            "remedy": "结构合理时如实说明"},
    "260": {"meaning": "某原子 Ueq 异常大", "causes": "鬼原子/部分占有/无序",
            "remedy": "检查差值密度支持，必要时删除或设占有率"},
    # ---- geometry (type 2) ------------------------------------------------
    "301": {"meaning": "主要残基中存在异常配位/化合价",
            "causes": "金属氧化态-配位数组合少见；或模型缺配体",
            "remedy": "对照合成先验说明金属价态与配位环境"},
    "306": {"meaning": "孤立氧原子（可能缺 H）",
            "causes": "配位水/羟基未加 H", "remedy": "说明 H 未定位的原因"
            "（对重原子附近的 O-H 常无法从密度定位）"},
    "331": {"meaning": "小分子内键长与常规值偏差大",
            "causes": "精修不稳、无序未建、或确实特殊成键",
            "remedy": "给出与文献可比结构的对照说明"},
    "340": {"meaning": "键长 s.u. 偏大", "causes": "数据/参数比低或弱数据",
            "remedy": "说明数据质量限制"},
    "341": {"meaning": "C-C 键精度低（bond precision）",
            "causes": "数据真实分辨率不足（GIGO：噪声壳层没砍）/弱衍射/"
                      "未建孪晶稀释了有效数据",
            "remedy": "按 estimate_resolution 客观截断噪声壳层后重精修；"
                      "仍差则如实说明数据极限，不硬压"},
    "371": {"meaning": "长 C-O 键提示需检查",
            "causes": "羧酸 C-O 单双键未区分或无序",
            "remedy": "核对羧酸配位模式（桥连/螯合）后说明"},
    "413": {"meaning": "短原子间接触（非键）",
            "causes": "对称生成的堆积接触；无序组分间伪接触",
            "remedy": "确认是否同一无序组内（PART）或真实短接触"},
    "430": {"meaning": "短的分子间供体...受体接触（D...A < ~2.9 Å）",
            "causes": "可能是漏建氢键的 H；也可能只是紧密堆积（专家案例："
                      "两个酯羰基 O...O 2.842 Å，无氢可加，属堆积）",
            "remedy": "先判断是否应有桥氢（质子化态/差图）；纯堆积接触则"
                      "在回复中解释"},
    "432": {"meaning": "短 X...Y 分子间接触",
            "causes": "堆积紧密或无序伪接触", "remedy": "同 413"},
    "482": {"meaning": "氢键 D-H...A 角度过小",
            "causes": "H 取向放置不佳（Jeffrey 标准 D-H...A > 100°）",
            "remedy": "重放 H 指向受体后精修；仍小则按弱相互作用解释"},
    "601": {"meaning": "结构含可容纳溶剂的空腔（void）",
            "causes": "孔道/空腔内溶剂未指认",
            "remedy": "能指认则建模合入化学式；弥散无序则 SQUEEZE/掩膜并"
                      "报告 electrons/void 与归属（掩膜纪律见 AGENTS）"},
    "931": {"meaning": "孪晶相关一致性指标异常",
            "causes": "存在未建模孪晶",
            "remedy": "加孪晶法则（TwinRotMat/set_twin）精修；不行回还原端"
                      "双畴拆分（HKLF5）"},
    "937": {"meaning": "WGHT 权重方案第三参数异常",
            "causes": "权重方案带了不常用的第三参数",
            "remedy": "删除 WGHT 第三参数并重精修生成 CIF（专家做法）；"
                      "或 OMIT 大误差点/查孪晶/对称性"},
    "939": {"meaning": "疑存在大 |Error/esd| 离群反射",
            "causes": "个别反射与模型严重失配（挡板遮挡/冰环/孪晶重叠）",
            "remedy": "Olex2 Bad reflections（或 lst 表）核查 |Err/esd|>10 "
                      "的点：确有仪器成因可 OMIT 并记录；成片失配则查数据侧"},
    "974": {"meaning": "PLATON 重算差图残差异常（与 971/973 同族）",
            "causes": "同 971：孪晶/元素指认/溶剂/吸收",
            "remedy": "同 971：游离峰查漏建，轻原子旁试无序，重原子旁重做"
                      "吸收/背景或重收数据"},
    # ---- data / refinement quality (type 3) -------------------------------
    "020": {"meaning": "Rint 明显偏大（与 RINTA01 同源：>0.10 C 级、"
                       ">0.15 B 级、>0.20 A 级；实践中 >0.18 即 B 级）",
            "causes": "晶体质量/吸收校正不足/对称性选高了/坏的采集轮次混入",
            "remedy": "核对 Laue 组与吸收校正；多 run 数据按轮分组查 Rint，"
                      "坏轮整体舍弃优于调 rejection 阈值；如实报告"},
    "022": {"meaning": "Friedel 覆盖率低/为零",
            "causes": "中心对称结构本就无 Friedel 对；或采集策略未覆盖",
            "remedy": "中心对称时属正常，说明即可"},
    "080": {"meaning": "最大 shift/su 偏大（精修未收敛）",
            "causes": "精修轮数不足；非正定 ADP；末端甲基等基团取向摆动",
            "remedy": "加大 L.S. 轮数再精修；仍不收敛则查模型（非正定原子、"
                      "可旋转甲基做无序/AFIX 137）"},
    "082": {"meaning": "R1 偏高", "causes": "无序/孪晶/数据质量",
            "remedy": "说明主要残差来源（孔道溶剂、无序），列出已尝试的处理"},
    "084": {"meaning": "wR2 偏高", "causes": "同 082；权重方案",
            "remedy": "同 082"},
    "088": {"meaning": "GooF 偏离 1", "causes": "权重未优化/模型欠拟合",
            "remedy": "用 run_shelxl(mode='adopt_wght') 收敛并采纳 SHELXL 的建议"
                      "权重后如实报告（optimize_weights 是 adopt_wght 覆盖不到"
                      "时才用的进程内搜索，大模型上可能跑很久）"},
    "094": {"meaning": "残余密度峰谷指标异常（与 097/098 同族）",
            "causes": "未建模孪晶/无序/吸收；专家案例（CCDC 2490844）：THF 旁"
                      "Max Peak 2.2 + 遍布怪峰 = 非切变孪晶，TwinRotMat 加"
                      "孪晶律后 B→C，根治需回还原端做孪晶拆分",
            "remedy": "残余峰怪异且分布广时先跑 audit_reflection_data/"
                      "TwinRotMat 排查孪晶，再考虑模型侧"},
    "097": {"meaning": "最高正残差峰较高（Max positive residual density）",
            "causes": "未建模原子/无序/吸收；高分辨数据的高角噪声也会抬峰"
                      "（专家案例：0.48 Å 数据 Max 1.0 报 B，SHEL 截 0.70 Å "
                      "降至 0.80 转 C）",
            "remedy": "给出峰位置与最近原子；无化学意义时按小步（~0.05 Å）"
                      "截断分辨率观察峰高单调下降，绝不为吸收残峰加假原子"},
    "098": {"meaning": "最深负残差峰较深（Min negative residual density）",
            "causes": "吸收校正不足/重原子附近截断效应/占有率或元素指认过重",
            "remedy": "给出谷位置与最近原子，说明成因（重原子 <1 Å 的涟漪"
                      "属正常并说明）"},
    "232": {"meaning": "Hirshfeld 检验（金属-配体键）差异大",
            "causes": "金属位点元素/占有率问题", "remedy": "同 230"},
    "110": {"meaning": "ADDSYM 检出模型可能存在漏掉的更高对称性",
            "causes": "还原/解析时选了过低对称（常伴 112/116 同族警报）",
            "remedy": "PLATON ADDSYM（本系统 check_symmetry）核查；确认升群时"
                      "最佳实践是回到还原端按正确对称性重新还原，专家案例：仅"
                      "做晶胞变换会多出 65 个缺失反射（PLAT911）被审稿人揪住，"
                      "重新还原则各项指标干净"},
    "112": {"meaning": "ADDSYM 建议更改空间群",
            "causes": "同 110；也见于晶胞选大一倍（寻峰设置不当）导致的"
                      "赝对称，专家案例：智能寻峰给出双倍体积晶胞，改传统"
                      "寻峰后晶胞减半、警报消失",
            "remedy": "同 110：check_symmetry 验证 → 回还原端重做；"
                      "怀疑晶胞加倍时核对寻峰/指标化设置"},
    "111": {"meaning": "ADDSYM 检出伪/额外对称性（与 110/112/113 同族）",
            "causes": "空间群可能选低了（专家案例：95 个伪对称提示）",
            "remedy": "check_symmetry/ADDSYM 核查升群；确认后回还原端按新群"
                      "重做（见 110）"},
    "113": {"meaning": "ADDSYM 建议检查更高对称性（同族提示档）",
            "causes": "同 110/111", "remedy": "同 110：ADDSYM 验证，否则给出"
                      "保持当前群的合理解释"},
    "245": {"meaning": "H 的 U(iso) 低于其载体原子的 Ueq",
            "causes": "无序组分的 H 用自由 Uiso 精修时可掉到母原子之下",
            "remedy": "改骑乘约束 U(iso)=1.2/1.5×Ueq(载体)（AFIX 默认），"
                      "不给 H 自由温度因子"},
    "314": {"meaning": "疑似缺失或放错的 O/N 上氢原子",
            "causes": "羟基/水/铵氢忘加或方向放错",
            "remedy": "核对该位点化学（差图峰+氢键网络）后补/转向氢；"
                      "确不该有 H 则解释质子化状态"},
    "336": {"meaning": "基团几何异常提示可能无序",
            "causes": "平均结构掩盖双取向（椭球拉长/键长异常）",
            "remedy": "检查差图与椭球形态，需要时做 PART 无序建模"},
    "410": {"meaning": "分子内 H...H 距离过短（<2.0 Å）",
            "causes": "加氢方向不当（专家案例：苯环 H 与亚甲基 H 1.836 Å）",
            "remedy": "重新理论加氢；或 DFIX 把两 H 距离限到 ≥2.1 Å；"
                      "真实拥挤则解释"},
    "412": {"meaning": "分子内 H...H 短接触（AFIX 组间）",
            "causes": "甲基/亚甲基取向不合理",
            "remedy": "专家做法：DFIX <目标距离> 0.01 两 H 标签，从略大于"
                      "当前值起试；或重置加氢取向"},
    "414": {"meaning": "H...H 短接触（C 档，与 415 同场景）",
            "causes": "同 415；特殊位置（如 3 次轴）水的氢常见",
            "remedy": "删掉问题 H 重新理论加氢（特殊位置水按对称约束放）"},
    "415": {"meaning": "分子间 D-H...H-X 短接触（<2.1 Å）",
            "causes": "相邻分子氢取向互相顶撞（专家案例：氨基 H 对二茂铁"
                      "Cp 环 H）",
            "remedy": "重放氢取向使其指向真实受体；无法避免则解释堆积"},
    "417": {"meaning": "D-H...H-D 供体氢互相短接触",
            "causes": "水/羟基氢没有指向真正的氢键受体（案例：水 H 与其"
                      "对称像 2.03 Å，A 级案例 1.50 Å）",
            "remedy": "找到附近真实受体（如 3.1 Å 内的 Cl/O），把 H 转向"
                      "该受体重精修，不是删氢"},
    "420": {"meaning": "D-H 供体氢无氢键受体（D-H without acceptor）",
            "causes": "O-H/N-H 氢的取向放置不合理（未指向可用受体）",
            "remedy": "找到合适的氢键受体，把 H 约束到供体-受体方向"
                      "（DFIX/HFIX 转向后重精修）；确无受体则给出化学解释"},
    "910": {"meaning": "θ(min) 以下的 FCF 反射缺失数偏多",
            "causes": "光束挡板（beamstop）θmin 设置过高；大晶胞的低角反射"
                      "被挡板遮挡",
            "remedy": "技术解（重测时）：增大探测器-晶体距离（专家案例："
                      "39→60 mm 后消除）；已有数据则如实说明采集几何"},
    "911": {"meaning": "θ(min) 与 sinθ/λ=0.6 之间的 FCF 反射缺失偏多",
            "causes": "完整度不足/挡板遮挡/扫描策略缺角",
            "remedy": "同 029/910；说明缺失来源"},
    "913": {"meaning": "FCF 中缺失的强反射数偏多",
            "causes": "过曝溢出被剔除/挡板遮挡低角强反射",
            "remedy": "重测可用衰减片补测强反射；否则说明剔除原因"},
    "971": {"meaning": "PLATON 重算差图存在靠近已有原子的显著正残峰（B 档）",
            "causes": "未处理孪晶/错误原子类型指认/未处理溶剂/其他模型错误；"
                      "重原子旁多为吸收校正或背景扣除不足",
            "remedy": "Q 峰游离→查漏建原子；轻原子旁→尝试无序处理；重原子旁→"
                      "重做吸收校正或换背景扣除重新还原（专家案例：M-Q1 "
                      "0.902 Å 处 2.6 e/A^3 触发 973+971，换背景扣除法重新"
                      "还原后 AB 级全消）"},
    "972": {"meaning": "PLATON 重算差图存在显著负残峰",
            "causes": "吸收校正/背景扣除不足；孪晶未拆",
            "remedy": "同 971；专家案例经孪晶拆分（双畴积分）解决"},
    "973": {"meaning": "PLATON 重算差图存在大正残峰（A 档，常在金属附近）",
            "causes": "同 971（973 为更严重档）",
            "remedy": "同 971：优先数据侧（吸收/背景/孪晶），A 级原则上必须"
                      "消除"},
    "934": {"meaning": "报告的与计算的 Rint 不一致",
            "causes": "数据经过预合并或掩膜贡献", "remedy": "说明数据处理链"},
    "941": {"meaning": "计算与报告的 F000 不一致", "causes": "组成/掩膜电子",
            "remedy": "确认 UNIT 组成；掩膜电子不计入 F000 属正常"},
    # ---- named checks (non-PLAT test names) -------------------------------
    "RINTA01": {"meaning": "Rint 超阈值（>0.10 C / >0.15 B / >0.20 A；"
                           "实践 >0.18 即 B，常与 PLAT020 同时触发）",
                "causes": "同 020：晶体质量/吸收/对称性选高/坏轮次混入",
                "remedy": "同 020；数据侧诊断（audit_reflection_data）优先"},
    "CELLZ01": {"meaning": "化学式×Z 与原子列表/对称性推出的晶胞内容不符",
                "causes": "UNIT/化学式没同步模型改动（删加原子、占有率、"
                          "掩膜溶剂计入与否）",
                "remedy": "按最终模型+掩膜归属重算化学式与 Z；掩膜电子是否"
                          "计入化学式要与 SQUEEZE 文档一致"},
    "CHEMW03": {"meaning": "化学式量与原子列表计算值不符",
                "causes": "同 CELLZ01（式量随化学式错）",
                "remedy": "同 CELLZ01"},
    # ---- misc informative -------------------------------------------------
    "004": {"meaning": "检测到聚合物结构（维度信息）", "causes": "MOF/配位聚合物",
            "remedy": "信息性提示，无需处理"},
    "606": {"meaning": "结构中存在溶剂可及空腔",
            "causes": "多孔材料本征特征", "remedy": "已用掩膜/SQUEEZE 处理时说明"},
    "609": {"meaning": "精修用了 ABIN 但 CIF 缺 SQUEEZE/掩膜文档",
            "causes": "掩膜贡献经 .fab 进入精修而 CIF 未写 _platon_squeeze_*",
            "remedy": "CrystalPilot 装配器写入 _platon_squeeze_details（含逐"
                      "空腔体积/电子数环）；旧节点缺明细时至少给出总量说明"},
    "720": {"meaning": "存在非标准原子标签", "causes": "标签与元素不一致"
            "（如 Zr 用了 FE01 标签）或含后缀",
            "remedy": "重命名为元素一致的标签（PLATON 按标签猜元素做键价）"},
    "794": {"meaning": "试探性键价和（BVS）信息", "causes": "信息性提示；注意 "
            "PLATON 按标签猜元素", "remedy": "核对与氧化态一致即可"},
    "802": {"meaning": "CIF 行超长等语法问题", "causes": "生成器未按 80 列折行",
            "remedy": "修正 CIF 写出"},
    "869": {"meaning": "与 SQUEEZE 相关的告警已被抑制", "causes": "信息性提示",
            "remedy": "无需处理"},
    "909": {"meaning": "θ_min 处缺低角反射", "causes": "光束挡板/采集起始角",
            "remedy": "说明仪器几何"},
    "912": {"meaning": "θ_full 以上缺失反射数目", "causes": "完整度",
            "remedy": "同 029"},
    "977": {"meaning": "reflns_number 与 hkl 数不一致", "causes": "预合并/掩膜",
            "remedy": "说明数据链"},
}


_AUTO_KB: dict[str, dict[str, str]] | None = None


def _auto_kb() -> dict[str, dict[str, str]]:
    """Fallback KB generated from the expert's CheckCIF dictionary series
    (589 codes with official meanings + curated remedies); lazy-loaded."""
    global _AUTO_KB
    if _AUTO_KB is None:
        import json
        from pathlib import Path
        p = Path(__file__).with_name("checkcif_kb_auto.json")
        try:
            _AUTO_KB = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - fallback KB is optional
            _AUTO_KB = {}
    return _AUTO_KB


def annotate(code: str) -> dict[str, str] | None:
    """KB entry for a PLAT 3-digit code or a named check (RINTA01...).

    Hand-curated entries (with case evidence) win; the auto-generated
    dictionary KB fills the long tail."""
    c = str(code)
    key = c.zfill(3) if c.isdigit() else c.upper()
    return KB.get(key) or _auto_kb().get(key)
