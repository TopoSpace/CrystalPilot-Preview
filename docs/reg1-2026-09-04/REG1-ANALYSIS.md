# 阶段 D 回归（reg1）分析：v33 模板 + P0 工具层之后的第一次泛化门禁

日期：2026-09-04（reg1-ext2 03:34–04:52 跑完；reg1-mof 04:53 起，结果见 §5，待补）
模板：`agents-v33`（7 461 字符），knowledge_mode = full，模型 gpt-5.6-sol / xhigh，L0 提示（"数据目录（只读）：… 请解这个结构。"）
机械稿：`REG1-EXT2-draft.md`（`ka1_report` 生成，逐格工具错误/打转/转向/易用性表）。本文只写人读出来的结论。

## 1. 一句话结论

五个从未跑过的 ext2 晶体（纯有机、Cu 配位聚合物、有机无序、两种孪晶）在 v33 + P0 上**全部在 12–19 分钟内交付、通过 checkCIF 解释门、结论与 CIF 一致、无窥视**；两格达到参考精度（hsl 与 cuox，R1 与参考差 0.0001），三格差在**无序组分未建**和**孪晶未建**上。评分器给出的 3 个 below_bar 里有 1 个是误判（hsl），另有 2 处评分措辞过重；这些都已定位到具体缺陷（§3）。

## 2. 结果总表（独立核对后的读数）

| 格 | 晶体 | 评级（原始 / 核对后应为 / 修复评分器后重评） | R1 agent / ref | 独立 emma | 主要差距 |
|---|---|---|---|---|---|
| hsl | 手性纯有机 P2₁2₁2₁ | below_bar / **publication 级** / acceptable（对称命名缺陷仍阻塞） | 0.0263 / 0.0264 | 13/13，rms 0.001 Å，元素零错 | 无（评分器被交付 CIF 的对称标签缺陷带偏，§3 D1） |
| cuox | Cu 草酸配位聚合物 P2₁/c | publication / — / publication | 0.0178 / 0.0179 | — | 无 |
| dbu | 有机 P2₁/n，PART 无序 | below_bar / below_bar（措辞应为"无序未建"） / acceptable（disorder_incomplete 规则） | 0.0626 / 0.0447 | 26/28（缺无序组分 A 的 C12A/C13A） | agent 认定"非谐热运动无法可靠离散建模"，未尝试 PART 拆分 |
| rz | 有机 C2/c，赝合并孪晶 | below_bar / — / below_bar | 0.1246 / 0.0996 | 21/21；1 个 N 标成 C | 孪晶未建（工具答"无候选"，§3 D3）；硝基 N 被标成 C 并被合理化为羧酸盐（§4.2） |
| nm | 有机 P-1，非合并孪晶陷阱 + PART 无序 | acceptable / — / acceptable | 0.0948 / 0.0526 | 23/25（缺无序组分 B） | 无序未建；参考 fcf 是去孪晶后的数据，agent 拿到的 hkl 也是，所以差距主要来自无序与权重 |

重评（9f107ca + D1/D2 评分器，2026-09-04 08:30）：hsl acceptable、cuox publication、dbu acceptable、rz below_bar、nm acceptable；reg1-mof 两格 hex 0.1341、cage 0.2226 均 below_bar（hex 原先在 literature 参考下被误判 publication）。

与 ka1 full 臂的唯一重叠是 hsl（= ka1 的 org）：两次都做到 R1 0.0263，用时 17 → 19 min。v33 把模板砍掉一半没有让这一格退步。

## 3. 本次暴露的缺陷（按层）

**D1 交付层（任何非标准设置都会触发）**：SHELXT 把 hsl 解在移了原点的设置里（模型的群写作 `P 21 21 21 (a+1/4,b,c-1/4)`）。`report/cif.py` 把符号后缀截掉，写出标准 `'P 21 21 21'` + IT 号 19，却附上移位后的算符环。cctbx 读它报 "Inconsistent symmetry information"，PLATON/checkCIF 同样会看到符号与算符不一致。修法（子代理进行中）：交付时把模型统一到标准设置（纯原点移位不动 hkl；轴变换要重指标 fcf），或写与算符一致的 Hall 符号；`write_outputs` 返回 `setting_change` 告知 agent。

**D2 评分器**：(a) 遇到 D1 这类标签冲突时应以算符环为准继续比对，并单独标记 `cif_symmetry_inconsistent`（仍是交付缺陷，但不该把"骨架未复现"这种更重的结论加上去）；(b) "骨架未复现"要区分"只差无序组分"（dbu 26/28、nm 23/25）；(c) "有更好节点"要排除不同空间群 / 参数翻倍的试探节点，nm 的 n0012 是 P1 试探（74 原子、414 参数）对 P-1（37 原子、207 参数），agent 拒绝它是对的。

**D3 工具层（P0 级）**：`set_twin(law='suggest')` 从未对任何晶体返回过候选律。原因两处：算符身份用 `str(rot_mx)`（对象地址），变换回工作基用 `rt_mx * rt_mx`（TypeError 被 try/except 吞掉）。返回文案还说"无候选 = 该度规下不可能有合并孪晶"，误导性极强。rz 的 C2/c、β = 92.3°，赝正交度规偏差 2.3°，在 3° 容差内，参考结构用的正是 `TWIN -1 0 0 0 -1 0 0 0 1`。已修（分支 `fix-twin-suggest`，bd79728）：整数矩阵做身份、C⁻¹RC 变换、报告度规偏差与 8° 内近失候选、非整数律标为网格合并孪晶、措辞改为"不排除非合并孪晶"。合成覆盖 C2/c 赝正交（rz 晶胞）、P-1 赝单斜、真三斜、Pnma、P4/n。

**D4 分析层（已修，8f39eb6）**：机械稿把五格全标"数据泄漏"，命中的是各格自己的 staging 目录，`ka1_report.staging_allow` 只认识 ka1 的三种晶体。白名单现在并入泳道清单的 data_dir/data_alias。

## 4. 过程读数（执行层、倾向、打转、工具易用性）

### 4.1 执行层
- 每格 125–158 次工具调用，出错 1–2 次；全部错误里 5 次是 `finalize_delivery` 第一次调用被拒（WP5 的设计：先拒、agent 逐条 waive 带理由、再收），这是协议不是故障；机械统计现已把它单列为 `expected_refusals`、不计入出错（3bdc361，机械稿已重出）。其余两次：hsl 的 `view_structure(view=…)` 传了不存在的参数（应为 `views`）；cuox 的 `read_skill(section='PLAT196')` 找不到节。
- 没有超预算的长调用，没有 detach 轮询，没有服务端丢下的工具（`transport_closed` 证据行零条）。WP1 的预算与 watchdog 在这五格里没被触发，说明小分子的计算量本来就在预算内。
- "转向"信号全是 `timeout` 触发词且其前无工具报错，是 agent 讨论 timeout_s 参数的措辞，不是真转向。

### 4.2 倾向与判断
- **C/N 裁决缺一个明确步骤**。T1.2 让无金属分支"C/N 不猜、标 C 并返回 element_uncertain"是对的，但 rz 把一个硝基 N 一路带到交付，并把它合理化为"羧酸盐 C1(O4)(O5)"、把分子写成内盐（agent 自己的组成 C30H24N2O9 对参考 C28H22N4O9：少 2 个 N、多 2 个 C）。几何上硝基与羧酸盐相近（X–O 1.22 vs 1.25 Å），能区分的是精修后的 Ueq（C 占 N 位会比相邻原子明显偏小）与密度档（N/C = 1.17）。待办 T1.2b：精修后对所有轻原子做 Ueq 相对邻居的元素一致性检查（现在只对金属键合的轻原子做），并在 `validate_structure` 里对"羧酸盐 C 的 Ueq 远低于其 O"这类组合给出提示。
- **无序不动手**。dbu 与 nm 都看到了无序迹象（dbu 的 verdict 写明 C15/C16 环段非谐运动；nm 试过 `split_o5_trial` 分支但 R1 变差就放弃），两格都没有走 `model_disorder` 的 PART 路线。这是 T1.6（model_disorder 验收闭环）要解决的：FVAR 回读与判词现在还不足以让 agent 相信拆分值得做。
- **孪晶**：rz 的 verdict 如实写了"预合并反射存在系统性强度异常，R 值偏高"，但工具告诉它"无候选"，它就止步了，诚实但无路可走。D3 修好后需要回归一次 rz。

### 4.3 打转
- 只有低成本读操作重复（`inspect_model(detail=atoms)` 3–4 次、`get_project_brief` 1–2 次、`run_checkcif` 3 次）；没有同参数重跑精修的真打转。cuox 的 `run_shelxl(l_s=30, adopt)` 重复 2 次是正常的收敛再跑。

### 4.4 工具易用性
- `finalize_delivery` 两步协议在五格里全部被正确使用（先拒后 waive），说明 WP5 的文案能被模型理解。
- `view_structure` 的参数名（`views` 复数）被误写一次；`read_skill` 的 section 匹配需要更宽松的别名（PLAT196 → 主题索引）。**已修**（分支 `fix-twin-suggest` b85da58）：`view=` 作为单数别名；section 键不是标题时退回到正文搜索，按各节自身正文的命中数选最具体的一节，返回 `section_matched_by`。

## 5. reg1-mof（hex + cage）

两格都是 B/full 臂（v33 模板 + 全知识）。hex 见 §5.1（掩膜没算收敛，已修）；cage 见 §5.2（最佳节点因 .res 写进了 SHELX 无法表示的数而永久丢失，已修）。对照 ka1 full 臂：hex 0.0833 → reg1 0.1341；cage 0.1642 → reg1 交付 0.2226（树内最佳 0.1636）。

## 6. 下一步

1. 已做：五个分支合并（6f9d10a…b239d29）、评分器 publication ⊂ acceptable（9f107ca）、SHELX 编码守卫（7ef11b1）；`--regrade` 两个战役与机械稿重出进行中。
2. reg2-mof（hex + cage 确认跑）：验证掩膜默认循环数与发散回退；与 ka1（hex 0.0833 / cage 0.1642）对照。
3. 回归：rz（孪晶律修复后）、dbu/nm（T1.6 之后）。
4. 评分器：`framework_reproduced_disorder_incomplete` 加匹配比例下限 0.85。

### 5.1 hex-full-r1（reg1）：R1 0.1341，与 ka1 full 臂的 0.0833 差 0.05：根因是掩膜没算收敛

- 同一数据、同一分辨率截断（SHEL 0.997，n_strong 2069 完全相同）、骨架原子相同（Zr1/Zr2 + 连接体 C1–C12 + O1–O6；reg1 多了末端 O 的 PART 无序、9 个 H、ISOR 限制）。**掩膜互换实验**（SHELXL L.S. 0，只算结构因子）：

| 模型 \ 掩膜 | 自己的掩膜 | 对方的掩膜 | 无掩膜 |
|---|---|---|---|
| ka1 模型 | **0.0834** | 0.2447 | 0.1814 |
| reg1 模型 | **0.1341** | 0.1982 | 0.1946 |

  无掩膜时两个模型只差 0.013；差距的主体（0.05）来自掩膜本身：ka1 的掩膜把 R1 从 0.181 压到 0.083，reg1 的只从 0.195 压到 0.134。
- ka1 的 agent 把 `solvent_mask` 的 `max_cycles` 一路加到 50 → 200 → 800（tools 臂 1000）去追收敛；reg1 的 agent 只用了 10 和 30。原因在**工具描述**：WP1 给 `solvent_mask` 加的 BUDGET 句写着"默认 10 个循环……降低 max_cycles 来限制开销（结果会报 solvent_mask_converged=false、电子数是下限，这是诚实，不是失败）"。这句话把"不收敛"说成可接受状态，agent 就不再追收敛了；而 BYPASS 不收敛的掩膜会低估溶剂贡献、直接抬高 R1。**这是 P0（WP1）措辞引入的回归**，正是阶段 D 门禁要抓的东西。
- 修法（战役结束后立即做，然后重跑 hex+cage 作确认）：默认 `max_cycles` 提高到足以收敛的量级并配自执行的墙钟预算（到期返回已达状态 + 明确的"再调用/加循环"建议）；描述改为"未收敛的掩膜 = 电子数下限 **且 R1 上限**，交付前必须收敛或说明"；`solvent_mask_converged=false` 的返回附一句直接的后果与下一步。
- 评分器另有一处口径问题：literature 参考下 `publication` 不要求绝对 R1 ≤ 0.10（hex 0.134 仍判 publication，而 `acceptable` 反而要求），须改为 publication ⊂ acceptable。

### 5.2 cage-full-r1（reg1）：交付 0.2226（无掩膜），树内最佳 n0152 0.1636 却再也打不开：根因是 .res 里写进了 SHELX 无法表示的数

- 时间线：96 min、481 次工具调用、4 次出错。agent 在 n0126 上做 `refine(mode=anisotropic, use_solvent_mask=true)` 得 n0152（R1 0.1636、wR2 0.447、GooF 1.23），整棵树的最佳节点，与 ka1 的 0.1642 持平。随后 `ghost_test` 两次报 "could not rebuild the session from n0152: IndexError: tuple index out of range"，回读同样失败；agent 回不到该节点，转而在旧节点上显式建了 19 个客体片段并弃用掩膜（推理里的理由是掩膜与客体原子"重复计数"），最终交付 0.2226。
- 根因（复现于项目副本 `workdir/probe-cage-ghost`）：n0152 的 model.res 第 92 行 C010 的各向异性 ADP 为 U11 0.69、U22 6.34、U33 16.58、U23 −9.96 Å²——smtbx 各向异性精修在这个原子上发散了（它多半不是 C，或者根本不是原子）。SHELX 原子卡上每个数都按"最近的 10 的倍数 m + p"解码：|p| ≥ 5 就不再是自由参数，16.58 被所有 SHELX 读取器（SHELXL、iotbx、Olex2）解成"−3.42 × 自由变量 2"，而 FVAR 只有 1 个值 → iotbx 在 `free_variable[m]` 处抛裸 IndexError。写出去的节点从此谁也读不回来。
- 修复（7ef11b1，元素无关的通用规则）：(1) 新模块 `io/shelx_codes.py` 固化 SHELX 编码规则；(2) 写入器 `write_res_text` 对 |值| ≥ 5 的自由参数拒写并点名原子与参数；(3) 读取器 `load_res_model` 预扫描，把裸 IndexError 换成"C010 U33 = 16.58169 引用了自由变量 2 但 FVAR 只定义了 1 个……回到父节点修 C010"；(4) `refine` 在提交节点前把发散的坐标/ADP 回退到本次循环前的值，用新的重参数化做一次只算目标函数的结构因子过程重算 R1/wR2/GooF（节点里的指标就是节点里的模型），返回 `diverged_atoms` + `note_diverged`，并把该原子插到 `adp_suspects` 首位。`tests/test_shelx_codes.py` 7 个测试；触及写入器/读取器/精修工具的 21 个测试模块 407 通过。
- 判断层读数：(a) 掩膜与显式客体二选一是对的纪律，但 agent 没比较两条路的 R1（0.1636 vs 0.2226），因为它已经打不开 0.1636 那条路；(b) 一个 U33 = 16.6 Å² 的 C 原子本应被当场点名"发散"，旧逻辑只按 Ueq > 0.20 报"U very large"，agent 看到后没有处理就继续；(c) `run_shelxt` 45 次、`wait` 92 次、`exec` 212 次，求解阶段大量试错，见机械稿 §3.2。
- 待确认：reg2-mof 重跑 hex + cage（修复后的默认掩膜循环数 + 发散回退）。

## 7. reg2-mof（hex + cage 确认跑，2026-09-04 07:49–09:41）

同数据、同参考、同模型（gpt-5.6-sol / xhigh）、同模板 v33；变化只有合并进 main 的修复（掩膜默认收敛 + 600 s 预算、SHELX 编码守卫、CIF 对称命名、T1.2b/T1.4/T1.6、评分器口径）。机械稿 `REG2-MOF-draft.md`。

| 格 | ka1 full | reg1 | **reg2** | 评级 | 墙钟 | 工具调用 / 出错 |
|---|---|---|---|---|---|---|
| hex | 0.0833 | 0.1341 | **0.0858** | publication | 38 min | 313 / 1 |
| cage | 0.1642 | 0.2226 | **0.1570** | below_bar | 72 min | 370 / 0 |

### 7.1 两处修复都被验证

- **掩膜收敛（§5.1 的根因）**：hex 的 agent 用默认参数调 `solvent_mask`（max_cycles 1000、timeout_s 600），掩膜在 92 个循环后收敛，R1 回到 0.0858，与 ka1 的 0.0833 同一档；reg1 那次只算了 10/30 个循环、R1 0.1341。另有一次早期模型上的掩膜 12 个循环即被判"发散"（f000s 1871 → 646），工具停下并如实报 diverged，这是模型问题被正确地推回给了模型，不是循环数问题。cage 的 6 次掩膜全部收敛（8–18 个循环）。
- **发散回退（§5.2 的根因）**：本次没有触发（没有原子的 ADP 跑到 |U| ≥ 5），`ghost_test` 3 次 0 错、`checkout` 6 次 0 错，reg1 的"最佳节点打不开"没有复现。两格合计 683 次工具调用只有 1 次出错（见 7.3）。

### 7.2 cage 仍 below_bar，但已是三次里最好的一次，且诚实

- R1 0.1570（参考 0.1395，分辩率截断不同不可比）；emma 判骨架复现、元素一致、交付即树内最佳。掩膜 + 67 个显式客体片段并用：这次 agent 没有像 reg1 那样把掩膜弃掉，而是掩膜留给无法建模的空腔（约 22.9%、约 670 e/cell），客体碎片显式放进去；但模型仍有约 40 个连通片段、87 个脱离主片段的原子，A 级警报 92 条（NPD、ADP 比、Hirshfeld、大位移）。
- agent 的交付状态是 diagnostic，unresolved 写了 9 条，全部是真问题（无合成先验、轻原子骨架不完整、Zr3/Zr7 分裂未归属、精修未严格收敛、完整度 0.736 / Rint 0.349、缺元数据、P2₁/c 只作工作群）。评分器同时挑出 **Zr7 CN=5**：Zr3/Zr7 是相距 0.75 Å 的分裂位点（0.59:0.41），配位球没有跟着分裂。
- **判断层读数**：T1.6 的 `disorder_acceptance` 其实给了警示，ZR7 的 Ueq 0.088 比模型中位数 0.278 低 3.2 倍（"过占的位点或元素过轻"），分裂距离 0.78 Å 刚好在数据 d_min 0.69 Å 之上；agent 仍以"占有率收敛、化学上说得过去、如实披露即可"保留（推理原文："keep based on occupancy instead of R… it's okay because of chemistry"）。一个孤立分裂的 Zr、周围配体全不分裂，在 Zr₆ 簇里化学上不成立；专家会先怀疑幽灵/错位。**待办（通用规则）**：`disorder_acceptance` 对重原子分裂组增加"配位球是否一致分裂"的读数，配位原子全部单点时判词降为 inconclusive 并直说原因，把警示从 ADP 一行提升为判词。

### 7.3 过程读数（执行层、倾向、打转、工具易用性）

- **执行层错误**：hex 1 次，`refine` 报"stored solvent mask is stale (f_mask 11289 vs 21774 reflections)"，agent 改了分辨率/数据后没有重算掩膜；工具提示的出路是"重跑 solvent_mask 或 use_solvent_mask=false"，其实 `refresh_mask=true` 一步就够，提示里补上（本轮已改）。cage 0 次。schema 拒绝两格均为 0；服务端丢弃工具 0；协议性拒绝 1（finalize 先拒后收，按设计）。
- **跑偏倾向**：cage 的"把差值峰当原子放进去"倾向仍在（`add_atoms_from_difference_map` 3 次、`integrate_difference_density` 5 次逐个验证 C₆H₆/C₂H₆O/CH₄O 假设、`edit_atoms` 7 次），最后留下 67 个客体片段，比 reg1 的 19 个多得多，但这次它至少每一块都做了积分密度核对，并在 unresolved 里承认骨架不完整。hex 没有明显跑偏。
- **原地打转**：机械信号里 cage `validate_structure`/`inspect_model`/`solvent_mask` 各同参数重复 3 次，读 transcript 是模型编辑后的复查，不是打转；hex `get_project_brief` ×3 属廉价重读。真正的成本项是 cage 求解阶段：`run_shelxt` 22 次（其中 17 次是 detach 轮询，覆盖 773 s），只有 2 组不同参数（组成 "C N O" → "Zr C O"），是等待，不是打转。
- **难调用的工具**（信号排序）：`read_skill` 两格共 10 次、8 种参数，agent 在按名字猜卡片（"framework-twin-pseudosymmetry-alarm"、"rint-reduction-strategies"、按 section "温度"/"A19" 取段），技能卡的**发现**成本仍高，内容回退只解决了"名对了段不对"的一半；`integrate_difference_density` 5 次 5 种参数是正常的逐片段验证；`add_hydrogens` hex 连续 3 次换参数（先加、再按载体类型补）。
- **路径线索**：两格的推理里都出现了从目录名读提示，hex 读到 "r25a" 和 **"reg2-mof"**，cage 读到 "pa1c-link"。数据泄漏审计干净（没有读 staging 之外的路径），但战役泳道名 `reg2-mof` 本身把"MOF"送给了 agent。**待办**：泳道目录名去语义（如 `lane-b2`），与 `anonymize_projects` 配套。
- **预算/取消**：没有任何工具超时或被丢弃；hex 38 min、cage 72 min，比 reg1（40 / 96 min）更短。

### 7.4 结论

hex 回到 publication，cage 从 0.2226 → 0.1570 且交付诚实：本轮 P0 + 阶段 D 的两处根因修复都成立。cage 离 acceptable 还差的是轻原子骨架/客体建模的判断力，不是工具故障；下一步（1）T1.6 加配位球一致性读数，（2）泳道名去语义，（3）rz（孪晶律）、dbu/nm（T1.6）回归。

## 8. reg3-rz（单格回归：孪晶律修复，2026-09-04 14:30–14:43）

主人的新规则：每次只跑一格、只回答一个问题。这一格回答的是"`set_twin(law='suggest')` 重写之后，agent 能否找到并精修 rz 的赝合并孪晶"（reg1 里工具答"无候选"，孪晶未建，R1 0.1246，below_bar）。机械稿 `REG3-RZ-draft.md`。

| | reg1 | **reg3** | 参考（沉积 CIF） |
|---|---|---|---|
| 评级 | below_bar | **publication** | — |
| R1 | 0.1246 | **0.1032** | 0.0996 |
| 孪晶律 | 未建（工具无候选） | TWIN 1 0 0 0 −1 0 0 0 −1，BASF 0.02365 | TWIN −1 0 0 0 −1 0 0 0 1，BASF 0.02337 |
| 墙钟 | 14 min | 12.7 min | — |
| 工具调用 / 出错 | — | 154 / 1（schema 拒绝 1） | — |

### 8.1 修复生效

- 工具这次给出了候选：度规比当前 Laue 群高出 2.3°（容差 3°），候选律附带"先试整数律、用 set_twin(matrix)+run_shelxl adopt 验证、BASF 稳定且 R 下降才算真孪晶"的说明。agent 先读了 `framework-twin-pseudosymmetry-alarm` 卡，判断"只有度规一条预警、强度分布没有平均化迹象，暂不先加孪晶"，在无孪晶模型把 R1 从 0.194 做到 0.122 后卡住，才回头测试候选律：BASF 从 0.2 起精修到 0.02365，R1 0.122 → 0.1105 → 0.1032。这是正确的顺序，先把模型做完，再用孪晶解释剩余的差距，而不是一开始就把孪晶当万能药。
- agent 的律 diag(1,−1,−1) 与沉积的 diag(−1,−1,1) 相差一个 C2/c 自己的二重轴（diag(−1,1,−1)），是同一条孪晶律的等价写法；孪晶分数 0.0237 对 0.0234。剩余 ΔR1 +0.0036 在 exact 参考下判 publication。
- 泳道目录 `l48a5add1`、数据别名 `s2c7e`：路径线索审计为空，rollout 里 "rz5267"、"reg1-rz"、"reg3" 零次出现，去语义生效。

### 8.2 过程读数

- **执行层错误** 1 次：`checkout({target: "solve_c2c"})` 被 schema 拒绝，agent 意图正确（回到分支 solve_c2c），只是把参数名猜成了 `target`。已改：`checkout` 接受 `target`/`branch` 作为 `node` 的别名，完全不给目标时返回活动节点、分支和最近节点表而不是裸拒绝。
- **打转**：`run_shelxl(l_s=20, adopt)` 同参数重复 2 次是收敛循环，不是打转。`run_shelxt` 3 次 3 种参数是求解阶段正常试探。
- **难调用的工具**：机械稿把 `read_skill` 连续 4 次换参数记为"参数试错"，核读 transcript 是 5 次全部成功的正常读卡（孪晶预警卡 + 审稿应答卡的 A23/A7/B35 三段），是分析器的误报，不是工具难调。已改：参数试错只在同一串调用里出现出错时才计入易用性信号，全部成功的换参列为浏览。§7.3 对 reg2 `read_skill` 的同类判断同样应按此修正（那两格的 read_skill 也是 0 错）。
- **T1.6b**：本格没有分裂组，配位球读数没有触发（rollout 里 `disorder_acceptance` 零次），验证它要等有分裂位点的格（cage 或 dbu/nm）。
- **预算/取消**：无超时、无丢弃。

### 8.3 结论

孪晶律修复成立；rz 从 below_bar 到 publication。下一格跑 dbu（T1.6 无序验收 + T1.6b 配位球读数首次在真实分裂上露面）。顺手做了两项：`checkout` 参数别名 + 无目标提示；分析器的"参数试错"只计有出错的串。

## 9. reg4-dbu（单格回归：T1.6 无序验收闭环，2026-09-04 14:49–15:05）

问题："合入 T1.6/T1.6b 之后，agent 会不会把 DBU 环的 PART 分裂建出来？验收读数在真实有机分裂上说了什么？"机械稿 `REG4-DBU-draft.md`。

| | reg1 | **reg4** | 参考（沉积 CIF） |
|---|---|---|---|
| 评级 | acceptable（disorder_incomplete） | acceptable（disorder_incomplete） | — |
| R1 | 0.0626 | **0.0626** | 0.0447 |
| 骨架匹配 | 26/28 | 26/28（缺 C12A/C13A，占有率 0.265） | — |
| 分裂建了吗 | 否（"非谐热运动无法离散建模"） | **画了又扔了**（见 9.1） | C9A/C10A ↔ C13A/C12A，0.735:0.265，位移 0.6 / 0.9 Å |
| 墙钟 | 16 min | 15.3 min | — |
| 工具调用 / 出错 | — | 154 / 0 | — |

### 9.1 发生了什么：工具把 agent 劝退了

- agent 这次**找对了原子**：从差值图（C16 旁 1.0 Å 处 0.94 e/Å³、C15 旁 0.91 Å 处 0.38 e/Å³）和大 ADP 判断环段 C00P/C00Q 无序，开分支 `dbu_disorder`，调 `model_disorder(atoms=[C00P, C00Q], occupancy=0.8, separation=0.6)`，占有率 0.8 与沉积的 0.735 很接近。
- 但它用的是工具的**缺省位移**：沿 ADP 主轴各 0.3 Å，A–B 0.6 Å；而差值峰说第二个位置在 0.9–1.0 Å 外（沉积模型里 C12A 离 C10A 0.90 Å）。工具随即在 pending 块里报"0.60 Å 低于数据 d_min 0.81 Å，两个位点不可分辨，s.u. 判词不可信"。agent 的推理："the tool is indicating that it's below dmin, which doesn't allow that. So, I wonder if I might need to adjust the separation to be set to 1 instead"——然后既没有把间距改成 1，也没有跑 `run_shelxl(adopt)` 读 s.u.，而是 `checkout laue_2m` 回到无分裂分支，做 adopt_wght 就交付了。分裂被画出来 36 秒后就被放弃，T1.6 的验收闭环一次都没转起来。
- 交付如实披露"C15/C16 存在未分辨的局部动态/构象无序"；R1、匹配数与 reg1 完全一样。

### 9.2 这是工具的问题，两处都改了

1. **第二位点该来自差值图，不是一个常数**。`model_disorder` 现在先在上一次 refine 的差值峰里找属于该原子的峰（离它 0.4–1.6 Å 且离它比离任何别的原子都近），有就把 B 放在峰上并写明"B from difference-map peak 0.94 e/Å³ at 1.00 Å"；没有才退回 ADP 主轴位移，并写明"无峰/无图"。各向同性原子有峰时不再以"没有分裂方向"拒绝。规则不带元素、不带晶体，四个新测试。
2. **pending 阶段的读数不能像判词**。separation 读数追加"这不禁止分裂：先用建议的 SADI/SIMU 精修再读 s.u.；若 B 是沿 ADP 轴画的而不是取自差值峰，先把它放到峰上"；pending 的 disposition 改为"在**这个分支**上立刻 set_restraints + run_shelxl(adopt)，本块里没有任何判词，间距/ADP 提示只是读 s.u. 时的注脚，不是弃用分裂的理由"。

### 9.3 过程读数

- 执行层错误 0、schema 拒绝 0、打转无（同参数重复都是编辑后复查）。`read_skill` 5 次全部成功，按新口径列为浏览。
- 判断层：识别无序位置正确、占有率估计正确；错在把工具的一句"分辨率注脚"当成禁令，这与 reg2 cage 把统计判词当化学许可是同一类错误的两个方向：agent 对工具返回的**判断性措辞**过度顺从。工具的措辞必须区分"读数"和"决定"，这一课已写进 T1.6 的两处文案。
- 泳道 `l8bcb3a8a`、别名 `s9b41`：路径线索为空。

### 9.4 结论

T1.6 的闭环在这一格没有被走完，原因在工具的缺省位移与 pending 措辞；两处已修。下一格用同一数据重跑（reg5-dbu），只回答"B 放在峰上、措辞改后，agent 会不会把分裂精修到底并读出判词"。

## 10. reg5-dbu（单格重跑：峰位放置 + pending 措辞，2026-09-04 15:11–15:25）

问题："B 放在差值峰上、pending 措辞改后，agent 会不会把分裂精修到底？"机械稿 `REG5-DBU-draft.md`。结果：评级、R1、匹配数与 reg1/reg4 完全相同（acceptable，0.0626，26/28），分裂又一次画了就扔。但这次工具和 agent 各错一半，且都能指认。

### 10.1 工具侧：修复生效，但配位球读数拿氢原子当了证人

- `model_disorder(atoms=[C00Q], occupancy=0.7)`（这次只分裂一个原子）把 B 放在了上一次差值图 1.12 e/Å³、距 C00Q 1.00 Å 的峰上，返回里写明 "B from difference-map peak 1.12 e/A^3 at 1.00 A"——峰位放置生效（沉积模型的 C12A 离主组分 0.90 Å）。separation 判"可分辨"（1.00 > 0.81），pending 的 disposition 明确写着"在本分支上立刻 set_restraints + run_shelxl(adopt)"。
- 但 T1.6b 的配位球读数把 C00Q 自己的骑乘氢 H15/H16/H14 当成了"单点邻居"，报 "2 of 5 single-site neighbours cannot be bonded to both components: H16 …"，而三个重原子邻居（C00P Δ0.08、C00M Δ0.20，均在各自位移可吸收范围内）其实全部一致。氢原子在 X 射线分辨率下是从载体生成的，不是独立观测；一个氢只跟一个组分成键是天经地义的。这是我在 T1.6b 里的实现错误，直接给了 agent 一句"or the second position is not an atom"。
- agent 的推理（分裂后 14 秒）："analyzing sphere reading … The second position might still be refined, fitting H electron density with carbon occupancy. However, it could incorrectly model H density as minor carbon … The tool's instructions suggest running now, but expert judgment allows for a rejection" → 19 秒时 `model_disorder(undo=fvar2)`，回 n0012 交付。它担心 1.0 Å 处的峰是氢的电子密度，而实际上 B 位点离最近的模型氢 H15 有 1.13 Å，1.12 e/Å³ 也远高于一个氢的量级；这些数字工具本来就算得出，只是没说。

### 10.2 已修（这一轮）

1. 配位球读数**不再把 H 计为邻居**；不一致的重原子邻居若在差值图里有自己的残余峰，读数直接点名"把它一起分裂：model_disorder atoms=[A, N]"，没有峰则说"先精修再读，或第二位置不是原子"——把一个二选一的岔路改成有证据指向的下一步。
2. `model_disorder` 返回 `evidence` 块：B 位点到最近模型氢的距离（是否坐在氢位上）、载体分裂前的 U_eq 相对模型中位数的倍数、ADP 各向异性比（本例 2.4× 与 7），agent 惯常的两个疑虑（"是不是氢"、"数据支不支持"）当场遇到数字。
3. 沉积模型的无序是两个原子（C9A/C10A ↔ C13A/C12A）；agent 这次只分裂了一个。有了第 1 条，C00P 若有自己的峰会被点名。

### 10.3 判断层读数（三次 dbu 合看）

三次都在"分裂画好、还没精修"这一步止损：reg1 说"非谐运动无法离散建模"，reg4 把分辨率注脚当禁令，reg5 把"可能是氢"当结论。共同点是 **agent 宁可在精修之前用一个假设否决分裂，也不肯让 SHELXL 的 s.u. 说话**：尽管 disposition 已经明说"本块里没有判词"。工具侧能做的（把读数做对、把证据说出来）这轮做完了；如果 reg6 仍在精修前弃用，剩下的就是流程纪律问题，应当作为一条 v33 式的流程规则提给主人决定（"画出的分裂只能由精修后的 s.u. 裁决，精修前不得 undo"），而不是继续改工具措辞。

### 10.4 结论

峰位放置修复成立；T1.6b 的氢原子缺陷已修并补了证据块。下一格 reg6-dbu 同数据重跑，只回答"读数改对、证据摆出后，agent 会不会精修到底"。

## 11. reg6-dbu（第三次单格：读数改对、证据摆出之后，2026-09-04 15:31–15:49）

问题："配位球读数排除氢、`model_disorder` 带证据块之后，agent 会不会把分裂精修到底？"机械稿 `REG6-DBU-draft.md`。结果：acceptable、R1 0.0626、26/28，第四次一模一样。这次 agent **根本没有调用 `model_disorder`**（0 次），修好的两处工具代码一次都没被走到。

### 11.1 发生了什么

- 17 分钟里的主线是质子化：`probe_site` 4 次逐个试 H 峰（N–H、O–H）、两个质子化分支、硝基 N 重新定型；中途一次 refine 把 H 也做成了各向异性（414 参数、R1 0.0523，评分器正确判为不可比），随后"riding H restored"回到 234 参数。
- 它看见了无序的全部证据并说了出来（+325 s 的推理）："C15–C16 1.416 Å 偏短……可能是 C16 无序和大 ADP 造成的表观缩短。**I should model the disorder for C16 and maybe C15**"——然后直接去 `write_outputs`。交付的 unresolved 写的是"最高差峰约 0.94 e Å⁻³，位于 C16 的氢范围；未引入证据不足的无序模型"。
- 这句"氢范围"就是它的否决理由：峰离 C16 约 1.0 Å，被当成"氢的位置"。可 H15/H16 已经骑乘在 C16 上，0.94 e/Å³ 也是一个氢的两三倍；这次证据块没机会说话，因为它连分裂都没画。

### 11.2 四次 dbu 合看

| 次 | 分裂画了吗 | 止损点 | 理由 |
|---|---|---|---|
| reg1 | 否 | 精修前 | "非谐运动无法离散建模" |
| reg4 | 画了（缺省 0.6 Å） | 画后 36 s | 工具说"低于 d_min"（措辞已修） |
| reg5 | 画了（B 在峰上） | 画后 19 s | "可能是氢密度"（配位球读数错算了氢，已修） |
| reg6 | 否 | 精修前 | "峰在氢范围，证据不足" |

工具侧三处真缺陷（缺省位移、pending 措辞、氢当证人）都已修，修的都对，但结果不动：**agent 每次都在 SHELXL 精修之前用一个假设否决分裂**，四次用了四个不同的假设。这不再是工具措辞问题，是流程纪律问题：v33 保留的正是"流程规则"这一类知识（ka1 的结论，知识层只在流程纪律上加分），而"画出的分裂由精修后的 s.u. 裁决、精修前不得否决"正是一条流程规则。我不再改工具措辞。

### 11.3 提给主人决定的两个选项（可并行）

**A. 模板加一条流程规则**（改 `crystalpilot/workbench/agents_md.py` 的 v33 → v34，需同步守卫测试）。建议原文（英文，与模板一致）：

> Disorder is decided by refinement, not by a hunch. When the map shows a residual peak 0.4–1.6 Å from an atom whose U_eq or anisotropy stands out, DRAW the split (model_disorder puts B on the peak), apply the suggested restraints, and run_shelxl(mode='adopt') on that branch BEFORE judging it. The refined free variable and its s.u. (disorder_acceptance) decide keep / restrain / revoke; "it might be hydrogen density", "the data may not support it" and "below d_min" are hypotheses to test, not reasons to undo a split that has not been refined.

约 90 字，模板预算（<8000 字符，现 7461）放得下。

**B. 工具侧再加一个主动读数**（不改模板）：`validate_structure` / `situation_report` 增加 `disorder_candidates`，把"残余峰 0.4–1.6 Å + 载体 U_eq 高于中位数 + ADP 拉长 + 与该峰最近的氢距离"四个数放在一起，按原子列出，并写明下一步是 `model_disorder`。这是把 §10.2 的证据块提前到分裂之前。元素无关、只参照模型自身。

我的建议：**A + B 都做，再跑一格 dbu**。A 是 ka1 已经证明有效的知识类型（流程纪律），B 让 A 有可执行的入口。如果只做 B 不做 A，按四次的经验 agent 仍会找到第五个假设。

### 11.4 其它读数

- 执行层 0 错、schema 拒绝 0、无打转；`probe_site` 4 次是逐峰验证（正常）。
- 泳道 `l555a0c7c`、别名 `s7a29`，路径线索为空。
- 三次重跑的墙钟 15.3 / 14.0 / 17.2 min，R1 完全一致（0.0626），说明这套数据上无分裂模型的终点是稳定的；差距 0.018 就是那两个原子。

## 12. reg7-dbu（主人决定 A + B 之后：模板 v34 + disorder_candidates，2026-09-04 15:59–16:22）

问题："有了流程规则和候选读数，agent 会不会把分裂精修到底并交付 DBU 环无序？"机械稿 `REG7-DBU-draft.md`。

| | reg1 / reg4 / reg5 / reg6 | **reg7** | 参考（沉积 CIF） |
|---|---|---|---|
| 评级 | acceptable ×4 | **publication**（修评分器后；修前误判 below_bar，见 12.3） | — |
| R1 | 0.0626 ×4 | **0.0475** | 0.0447 |
| 骨架匹配 | 26/28 | **28/28** | — |
| 无序模型 | 无 | DBU 三碳链两构象 **0.707(6):0.293(6)**，16 条限制，237 参数 | C9A/C10A ↔ C13A/C12A，0.735:0.265，192 参数 |
| 墙钟 | 14–17 min | 22.7 min | — |
| 工具调用 / 出错 | — | 236 / 6（含 schema 拒绝 2，见 12.4） | — |

### 12.1 这次走完了整条链

- `validate_structure` 在分裂前 95 秒就列出了候选：C00Q，残余峰 1.34 e/Å³ 距 1.03 Å，U_eq 为模型中位数 2.2×，ADP 比 5.7，"模型里没有氢可混淆"。
- agent 开分支 → `model_disorder(atoms=[C00Q])`（B 落在 1.11 e/Å³ 的峰上，配位球一致）→ `set_restraints`（SADI/SIMU）→ `run_shelxl(adopt)` → **verdict supported，FVAR 0.702(7)**。然后它自己意识到"C00M 和 C00P 是两种构象的铰链"，回到父节点重来：`model_disorder(atoms=[C00M, C00P, C00Q])`（C00P 的 B 取自 0.41 e/Å³ 的峰，C00M 无峰走 ADP 轴，返回里都写明了来源）→ 限制 → adopt → supported，0.702(7) → 权重采纳后 0.707(6)。
- 它没有停在第一个 supported：又对候选表里的 O004、O00A、C00G 各开分支试了一遍（分别 supported 0.55(3)、0.59(2)，C00G 的配位球读数判不一致），最终以"残差极值只剩 +0.25/−0.30，O3/O6 分裂在精修中坍缩"为由用 `mark_adjudicated` 逐条驳回，只保留三碳链。这正是"读数是证据、决定归精修与化学"的用法：supported 只说明零假设被排除，是否保留仍看几何和残差。
- 交付：R1 0.0475（沉积 0.0447，Δ +0.0028）、wR2 0.120、GooF 1.01，无序在 SUMMARY 里如实写为 0.7073(61):0.2927(61)。沉积模型只分裂两个原子，agent 分裂三个（多一个铰链），占有率 0.707 对 0.735，差别在建模选择的量级内。

### 12.2 A 与 B 各起了什么作用

- B（候选读数）把"要不要建"变成了"该建哪个、B 放哪、下一步是什么"，agent 的推理里直接引用了候选表（"testing disorder candidates … the top two candidates"）。
- A（流程规则）体现在它**没有在精修前否决**：四次都出现的"先假设后放弃"这次没有发生；三次 `run_shelxl(adopt)` 都在同一分支上完成后才比较节点。规则的措辞被它复述为 "the rule doesn't have …/ the user agents are explicitly …"，说明模板条款被读到并当成了操作约束。
- 无法从一格分离 A、B 各自的贡献；按 ka1 的方法论，这也不必要，两者本来就是"流程纪律 + 让纪律可执行的读数"的组合。

### 12.3 评分器的第二个真缺陷：盐/共晶的 precision

- 修前评级 below_bar，理由 "framework not reproduced (emma solved=false, 28/28 matched, fraction 1.0)"：emma 的公平过滤把参考缩到最大成键片段（15 个原子，一个离子），模型却理所当然保留了两个离子（29 个），precision = 15/29 = 0.517 < 0.60 → solved=false。规则原文甚至写明"they lower PRECISION without lowering recall"——设计时就知道。之前四次 dbu 同样 15/26 = 0.577，被 disorder_incomplete 的兜底遮住了。
- 修法（75c8ed9，通用）：与"另计"的参考原子（次级片段、占有率 < 0.5 的客体）匹配上的模型原子不算多余，从 precision 分母里去掉；分子不加。合成盐固件三个测试：模型多建反离子不再受罚、真正凭空多出的原子照样压低 precision、单片段参考不变。重评 reg7 → **publication**（precision 0.938，13 个原子按"另计"扣除）。reg1-ext2 按新口径重评见 PLAN。

### 12.4 过程读数

- 执行层错误 6 次（236 次调用）：`run_shelxl` 2 次拒跑，"2 riding-H group(s) carry an AFIX code SHELXL's connectivity check would refuse"，分裂后的碳上骑乘氢的 AFIX 与新连通性不符，工具按设计拒绝并指明用 add_hydrogens 重派或删除，agent 照做后通过（这是无序建模里氢处理的真实摩擦点，值得让 `model_disorder` 在分裂时直接把载体上的骑乘氢按组分重派，待办）；`compare_nodes` 2 次 schema 拒绝，用了 `node_a/node_b` 而不是 `a/b`，与 reg3 的 `checkout({target})` 同一类参数名猜测，本轮顺手加了别名；`inspect_model` 1 次，猜了 `atom_labels` 参数（工具只接受 detail），报错即改；`view_structure` 1 次，还没有模型时就调用（"model has no atoms"）。
- `run_shelxl(adopt)` 同参数重复 7 次是分裂，限制，精修的循环，不是打转。路径线索为空（泳道 `lb3fbfe1a`、别名 `s1d6f`）。

### 12.5 结论

A + B 生效：dbu 从四次 acceptable 到 publication，R1 从 0.0626 到 0.0475，无序按沉积同一方向建出并如实报告。顺带修了评分器对盐/共晶 precision 的偏差。下一格建议 nm（同类无序 + 非合并孪晶陷阱），验证规则在另一颗晶体上是否同样生效。

## 13. reg8-nm（单格：v34 + disorder_candidates 推广到第二颗有机晶体，2026-09-04 16:34–16:47）

问题："无序流程规则能否推广到 nm（乙基 C15B/C16B 分裂），nm 高出沉积 0.042 的 R1 差距还来自哪里？"机械稿 `REG8-NM-draft.md`；完整日志包 `workdir/campaigns/reg8-nm/nm-full-r1/logs/`（rollout.jsonl 495 条、sse.jsonl、engine-events、mcp_server.jsonl、nodes.json、results、MANIFEST.json），项目目录 `H:/CrystalPilot-campaigns/l44b0258e/peeb65cea/` 保留全部 SHELXL 作业与节点。

| | reg1 | **reg8** | 参考（沉积 CIF） |
|---|---|---|---|
| 评级（修评分器后） | acceptable | acceptable | — |
| R1 | 0.0948 | **0.0948** | 0.0526（沉积）/ **0.0942（沉积模型在交付数据上重精修）** |
| 骨架匹配 | 23/25 | 23/25（乙基 C15B/C16B 未建，占有率 0.357） | — |
| 墙钟 | 12.5 min | 12.0 min | — |
| 工具调用 / 出错 | — | 156 / 2 | — |

### 13.1 最大发现：R1 差距是基准数据的缺陷，不是 agent 的

- nm 的参考是"非合并孪晶"（题目原话），沉积的 fcf 是 **HKLF 5 孪晶精修**输出的 LIST 4：每一行是一条观测到的复合反射（两个畴的重叠贡献）连同它自己的复合 Fc²，畴归属没有写进 fcf。我们的 `ref.hkl` 直接由它派生：10 410 行只有 5 378 组不同 hkl（按 −1 合并后 3 046），3 239 组重复、最多 8 次，其中 53.5% 在 3σ 之外互不一致。SHELXL 以 HKLF 4 读入时把不同重叠比例的复合强度合并平均，单畴模型无法拟合。
- 验证：把沉积 CIF 的原子按 HKLF 4 在同一份 hkl 上精修（`workdir/nm-transplant`，L.S. 10，非 H 各向异性、H 自由各向同性）→ **R1 0.0942 / 2715 Fo > 4σ / 3046 合并数据，wR2 0.30**。沉积的 0.0526 在这份数据上不可达；reg1 与 reg8 的 0.0948 都坐在这个下限上。
- agent 的表现是对的：`audit_reflection_data` 报 42.3% 重复组严重不一致（最差 (1,−3,2) χ²_red 5910），agent 在 unresolved 里写"42.3% 重复反射组严重不一致；无原始帧，无法区分缩放误差与复合晶体/非重叠孪晶"，并试了 P1（R1 0.082，414 参数）后由 `check_symmetry` 判"模型服从额外对称元素 → P-1"回到 P-1。它没有为压 R1 做任何无化学依据的操作。
- 修复（b4deb00、01c2d13、都是通用规则）：① 评分器新增 `reference_on_delivered_data` 臂，沉积模型（内嵌 res 或经 iotbx.cif 读原子环 + 平台写入器）在**交付数据**上重精修；差 > 0.01 时以它为 R1 基准并在 `r1_delta_basis` 里披露（nm：0.0942，Δ 变为 +0.0006）；② `audit_reflection_data` 对"同 hkl 重复 > 2 次、大量 3σ 外不一致、无批号"给出 HKLF 5 导出签名与"单畴模型有 R1 下限，写进 unresolved、不要追"的读数；③ publication 门改读 framework 诊断，未建的无序组分（这里的乙基 B 组分）留在 acceptable；④ 数据侧 `benchmark/data_ext2/twintrap_nm_cod2229074/REFERENCE-CAVEAT.md` 记录测量（评分器会把它带进 GRADE.md 的"参考本身存疑"行）。重评：reg8/reg1 的 nm 均 acceptable（Δ +0.0006，无序不完整）。
- 教训：**exact 参考的 R1 必须先验证"沉积模型在交付数据上能否复现"**：这一条现在由评分器自动做。

### 13.2 无序规则在 nm 上的表现

- 候选读数工作正常：`validate_structure` 每次列出 5 个候选（峰 0.4–0.7 e/Å³，U_eq 比 0.8–1.6，ADP 比 1.7–5.1）；沉积的乙基碳（agent 标签 C00M → 改名后 C15）一直在表里（0.74 e/Å³ 距 0.96 Å，后期 0.43）。
- agent 按规则做了：开分支试 O005（B 落在 0.37 e/Å³ 的峰上，SADI+SIMU，adopt → supported 0.51(2)，但 R 上升、SADI 违反 10σ、分裂坍缩到 0.58 Å → 驳回）；试 C00J、再 C00J+C00D 共用 FVAR（supported 0.73(5) → compare_nodes 后驳回）。判词 supported 只说明零假设被排除，agent 用几何与 ΔR 否决，这是规则要的用法。
- 但它**没有测试乙基本身**（C15/C16），而是以"代表性试验已完成"一句把 5 个候选全部 `mark_adjudicated`。在复合数据上乙基分裂也未必立得住（沉积模型是在 HKLF 5 上才做出的），所以对结果影响不大；但"以两次试验代表全部候选"是一个判断层捷径，候选读数应当把"已试/未试"记下来，让 `situation_report` 直接说"C15 未试"。
- 一次 `run_shelxl` 拒跑：分裂后骑乘氢的 AFIX 与新连通性不符（与 reg7 相同的摩擦点）；agent 重跑 `add_hydrogens` 后通过。`model_disorder` 分裂时重派载体骑乘氢仍是待办。

### 13.3 执行层错误（2 / 156）

| 工具 | 次数 | 原因 | 判定 |
|---|---|---|---|
| `view_structure` | 1 | 会话里还没有原子时就调 `state=cell`（"model has no atoms"） | 顺序错误，agent 立即改道；可让工具在无原子时返回晶胞图而不是报错 |
| `run_shelxl` | 1 | 分裂后骑乘氢 AFIX 与连通性不符，工具按设计拒跑并指明修法 | 设计内的拒绝；根治在 model_disorder 重派 H |

schema 拒绝 0（reg3 的 checkout、reg7 的 compare_nodes 别名修复后没有再出现同类）；协议性拒绝 1（finalize 先拒后收，8 条元数据警报逐条 waive）。

### 13.4 跑偏倾向、打转、难用的工具

- **跑偏**：无。P1 试验是对 42% 不一致的合理假设检验，一个 check_symmetry 就收回来了；没有为压 R1 加原子、删原子或换群。
- **打转**：`situation_report` 同参数重复 2 次是 agent 想看"已裁决的候选还会不会列出来"（它发现 open_items 在 mark_adjudicated 之后仍列出候选，这是一个真实的小缺陷：`situation_report` 的候选列表没有读裁决记录）；其余同参数重复都是编辑后复查。轮询 0。
- **难用的工具**：无带出错的换参串。`read_skill` 未调用（v34 模板把要点写进了铁律）。
- **工具面的三个优化点**（本格新发现）：① `situation_report`/`validate_structure` 的候选列表应带"已试/已裁决"标记并读 `mark_adjudicated`；② `ingest_vendor_data` 在导入时就应报"HKLF 4 文件里同 hkl 重复 N 组、最多 M 次"（现在要到 audit 才知道）；③ `view_structure` 无原子时给晶胞/数据视图而不是报错。

### 13.5 结论

规则推广成立：agent 在第二颗晶体上也走了"画，限制，精修，读 s.u."的完整链，并用几何/ΔR 否决了统计上 supported 但化学上不成立的分裂。nm 的 0.042 差距被证明是基准数据缺陷，评分器与审计工具都已按通用规则修正。

