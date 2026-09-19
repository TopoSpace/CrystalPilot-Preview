# p770 / p780 练习战役 transcript 深挖审计

审计对象（只读）：
- p770-t1 = `workbench/r10-p770-refine/CrystalPilot Results/task_20260830_140644/transcript.jsonl`（711 行，14:06–15:06）
- p770-t2 = `.../task_20260830_143110/transcript.jsonl`（563 行，14:31–14:59，SHELXT 救场轮）
- p770-t3 = `.../task_20260830_151405/transcript.jsonl`（1579 行，15:14–17:55，第 2–8 轮共 7 个 turn）
- p780-t1 = `workbench/r10-p780/CrystalPilot Results/task_20260830_132717/transcript.jsonl`（493 行）
- p780-t2 = `.../task_20260830_142504/transcript.jsonl`（213 行）

交叉印证：各 task 的 SUMMARY.md / VALIDATION.md / REPORT.json（t1 SUMMARY 披露 P–C 回收阈值、t3 SUMMARY/REPORT 披露 adopt/H0 恢复链与 unresolved 清单，与 transcript 一致）。

行号 L# 均指对应 transcript.jsonl 的物理行号。已知缺陷 #9–#14（PART 盲加氢、rename 不联动 disorder_groups、键长门 1.20–1.80、约束表 PART 盲、>4字符标签失步、金属 π/σ、线性 sp 门、adopt 重放丢 H、峰表不统一、add_atoms H 距离门、审批守护哨兵）只在有新细节时提及。t3 的 7 条用户消息（L1/L430/L874/L1124/L1154/L1212/L1504）证实这些修复是在轮次之间陆续部署的，transcript 本身就是这些缺陷的原始证据链，不再重复立案。

---

## 1. 工具失败统计表

MCP 工具调用总计约 624 次，`ok=false` 或 schema 失败共 34 次（≈5.4%）。

| 工具 | 调用 | 失败 | 失败原因分类（出处） |
|---|---|---|---|
| run_shelxl | 54 | 6 | 5×`L.S. 0 incompatible with ACTA`（工具设计：check 模式不剥 ACTA；t1 L247、t2 L104、t3 L374/L1079/L1364）；1×SADI/SAME sfac 类型失配致 job.res 为空（t3 L234，重放/校验问题） |
| refine | 53 | 6 | 3×`InvalidConstraint: bad connectivity`（C7 secondary_xh2 ×2：t1 L598、t3 L1151；C25 staggered_xh3 ×1：t3 L954，均属约束连接表门/PART 盲家族）；2×`stored hydrogen constraints are stale`（t3 L337、p780-t1 L206，改模后约束失步）；1×参数枚举 `'iso'` 不合法（p780-t2 L28，schema 摩擦） |
| model_disorder | 12 | 4 | 2×`ValueError: cannot read element from ''`（散射体代理失效，t2 L318、t3 L54，见问题 #6）；1×无法为 SHELXT 风格标签 C014 派生 B 部件 4 字符标签（t2 L334）；1×各向同性且无 second_sites 的信息性拒绝（t2 L342） |
| add_hydrogens | 40 | 2 | 2×smtbx `covalent_radii.table('')` 原始 traceback 崩溃（t2 L323、t3 L61，模型中残留空散射类型时整调用崩溃） |
| assemble_asu | 22 | 2 | 2×`did not reduce detached atoms (12->12)`，把"合法独立客体（晶格苯）"当失败（t1 L569、t3 L329） |
| add_atoms_from_difference_map | 16 | 2 | 2×`no stored difference-map peaks - refine first`（t3 L1003/L1011，节点操作后峰缓存丢失；峰表统一修复前） |
| create_start_model | 2 | 2 | 2×`dials.hkl not found ... run scale_and_export first`，不支持现成 HKLF4 起模（t1 L18、p780-t1 L45） |
| list_mcp_resources / _templates | 6 | 6 | MCP `resources/list` 未实现 / 返回空（t3 L6/L7 Method not found；p780-t1 L5/L7、p780-t2 L6/L7），会话启动例行噪音 |
| rename_atoms | 8 | 1 | `labels not in model: ['H107X']`，工具报的新原子标签在节点提交时已被自动改名（t3 L1236，见问题 #15） |
| optimize_weights | 12 | 1 | 基线精修被 C7 约束缺陷连坐（t3 L759） |
| compare_nodes | 12 | 1 | schema 参数名是 `a/b`，agent 传 `node_a/node_b` 被拒（p780-t2 L67） |
| change_space_group | 2 | 1 | 拒绝主动降群 C2/c→C2（p780-t1 L287，见问题 #10） |
| 其余 18 个工具 | ~347 | 0 | — |

shell 命令共 351 条（t1 114 / t2 52 / t3 120 / p780-t1 41 / p780-t2 24），非零退出约 30 条：约 1/3 是 agent 自写 cctbx 脚本的崩溃-修复迭代，约 1/3 是 PowerShell 引号/通配符/glob 摩擦，3 条 EXIT=124 超时（t1 L34 递归搜盘、t1 L67 cf_rescue、t3 L564 审计脚本），其余为 rg 无命中等良性退出码。审批 625 次全部 accept，无拒绝。

---

## 2. 问题清单（新问题 / 已知缺陷的新细节）

严重度：P0=会产出错误结果或毁坏状态；P1=堵塞主流程、逼出野路径；P2=摩擦/打磨项。

**#1【P0】无项目级会话锁：两个 agent 并发写同一工程，反射文件被当场调包**
- 现象：t1 运行中（14:31–14:59 窗口）发现"外部流程"写入 start.ins、注入节点 n0012（t1 L181/L228/L229 消息）；随后 t1 的 run_shelxl(check) 得到假 R1=0.687/GooF=9.976（t1 L251），排查发现工作区 `crystal.hkl` 已被并发会话（即 t2）换成 446114 字节的 HKLF5 文件而 SHELXL 指令仍是 HKLF4（t1 L260 命令输出证实 crystal.hkl 与 twin_hklf5.hkl 同尺寸；L261 消息定位根因；L267 从备份恢复 363390 字节 HKLF4）。t2 侧对应操作见其 L119（建 hklf5_work）与 L276（hklf4_restore）。
- 根因猜测：refine 会话对反射数据的绑定是"共享可变路径 `crystal.hkl`"而非每节点不可变引用；平台无任何工程锁/租约，第二个会话可静默 attach 同一 `.crystalpilot`。
- 修复建议：工程目录加会话锁（或显式 takeover 流程）；节点记录反射文件哈希，run_shelxl/refine 前校验哈希不符即拒绝并指名冲突方。
- 备注：t1/t2 因此各自交付了一份 final.cif（H66 R1=0.0666 vs H66 前身 R1=0.0686），交付物冗余也源于此。

**#2【P0】起模入口指针失步：导入成功但重载回零原子模型（两次独立复现）**
- 现象：t1 Patterson 种子导入后 `start.res` 坐标正确，但 `context.json` 的 `start_model` 仍指向零原子 `crystal.ins`，重载回空模型（t1 L174 消息）；t2 HKLF5 变换导入时同样"导入器已生成 start.res，会话重载却指向此前无原子 start.ins"（t2 L249 消息）。
- 根因猜测：solve/import 写出新起模文件后不回写会话的 start_model 指针；reload 逻辑按固定文件名取起点。
- 修复建议：import/ingest 成功时原子数>0 则强制更新指针并在返回摘要中回显所用起模文件路径+原子数；reload 后原子数与导入数不一致时报错而非静默。

**#3【P0→已部分暴露】交付装配链状态失同步：CIF/RES/FVAR 不一致、失败时静默复用旧 job**
- 现象（t3 第 4 轮与第 7 轮反复出现）：`final.cif` 取自 SHELXL check job（FVAR 已被自由精修移动），`final.res` 取活动节点旧 FVAR（t3 L1075、L1325 消息）；更严重的是 `L.S.0` 失败后"写出器仍复用了上一份 20 周期 job，CIF/RES 不一致问题没有被解决"（t3 L1084 消息）；安全回退文件复审仍见 RES 只有 46 个非零 PART H 而 CIF 有 106 H（t3 L1105 消息）。第 7 轮靠 20+20+50+100 周期 SHELXL + 手工回写 H 坐标（L1358/L1399/L1432/L1463 edit_atoms）才闭合三方一致。
- 根因猜测：write_outputs 从"最近一次 SHELXL job 目录"取 CIF/FCF、从活动节点取 RES，两者无同源校验；run_shelxl 失败不使旧 job 失效。
- 修复建议：write_outputs 强制校验 CIF/RES 的原子数、H 数、FVAR（容差内）一致，不一致即 fail；run_shelxl 失败时标记 job 目录为 invalid，写出器拒绝复用。
- 已知关联：adopt 丢 H（#12）已修，但"装配自洽"是独立问题，修复后仍复现（L1325 在第 7 轮）。

**#4【P1】create_start_model 只认 DIALS 帧管线，现成 HKLF4 无类型化入口**
- 现象：两个战役第一步都撞死：`dials.hkl not found ... run scale_and_export first`（t1 L18、p780-t1 L45）。两处 agent 都被迫走 shell 跑 `python -m crystalpilot.cli solve`（t1 L29；p780-t1 L50 命令内联，产物 runs/run_c12afabd86 于 L52 读取）再 import_cif_model 收回。
- 根因猜测：起模工具与帧管线硬耦合；SAINT/TWINABS/XPREP 已还原数据是 MOF/练习数据的常态入口，未覆盖。
- 修复建议：create_start_model 增加 `hkl_path/ins_path` 直接入口（等价 CLI solve 的类型化封装），或提供 solve_from_hkl 工具。

**#5【P1】import_cif_model 三连坑：hkl_path 触发 0 原子静默成功、DDLm 标签不识别、Z 元数据错误**
- 现象：
  (a) p780-t1 L56 带 `hkl_path` 参数的导入返回 ok=true 但 `imported_atoms: 0` 且空间群回落 P-1；L84 去掉 hkl_path 重试才导入 11 原子/C2/c；期间 agent 靠读平台源码定位（L70 命令 rg tools_analysis.py）。
  (b) t2 L226 消息：cctbx 写出的 `_cell.length_a`（DDLm）不被识别，CIF 被解释成 1 Å P1 晶胞并"拒绝了全部原子"。
  (c) p780-t1 L310 消息：粗解 CIF 把整晶胞组成当 Z=1，公式/密度/F(000) 全错；agent 手工制作 `intermediate_z8_import.cif`（L322 导入 z=8.0）与 `metadata_corrected_import.cif`（L415）纠正。
- 根因猜测：(a) hkl_path 分支解析异常被吞掉后仍返 ok；(b) 只支持传统 CIF1 标签；(c) 求解器 CIF 的 formula/Z 语义与导入器不对齐。
- 修复建议：imported_atoms==0 一律 ok=false；晶胞标签解析失败必须报错而非回退 1 Å P1；导入摘要中 Z 与 formula 联动校验（Z×ASU 组成 vs cell 组成）。

**#6【P1】model_disorder 多原子拆分：散射体数组扩容使元素代理失效，失败调用还留脏状态**
- 现象：`ValueError: cannot read element from ''`（t2 L318、t3 L54）；agent 诊断为"多原子拆分时内部散射体数组若没预留容量，加入第一个 B 位点后使后续元素代理失效；单原子拆分成功"（t3 L100 消息），workaround 是先做一次坐标不变的 edit_atoms(move) 迫使数组重建（t3 L108/L137/L168 无操作 move，随后 L172–L184 四组连续拆分成功）。另外 t2 L345 消息：一次失败调用"留下了未提交的 C28 临时状态"污染该试验节点，失败不回滚。
- 根因猜测：持有 cctbx scatterer 引用跨插入操作使用（典型 flex 数组 reallocation 失效）；异常路径缺 try/rollback。
- 修复建议：拆分前按目标数量 reserve 或全程用索引不用引用；工具失败必须恢复调用前模型快照（原子性）。
- 严重度说明：脏状态部分够 P0，但影响面被节点链隔离，综合 P1。

**#7【P1】add_hydrogens 在异常模型上整体崩溃且泄漏原始 traceback；elements=[] 被接受**
- 现象：t2 L323、t3 L61：`smtbx.utils.connectivity_table` → `covalent_radii.table('').radius()` 原始 traceback 直接进 result；触发条件是模型残留空散射类型（#6 的连带）。`elements: []` 这种空参也照常进入执行。
- 修复建议：入口先校验全部散射类型非空并给结构化错误；空 elements 快速失败。P1（崩溃）+P2（体验）。

**#8【P1】run_shelxl(check, l_s=0) 与 ACTA 不兼容，同一坑 5 次，跨 3 个 task 无护栏**
- 现象：t1 L247、t2 L104、t3 L374/L1079/L1364 完全相同的错误：`** L.S. 0 incompatible with ACTA **`，job.res 为空。第 7 轮 agent 明确定性"这是格式限制，不是模型失败"并改用 L.S.1（t3 L1365 消息）。"对账不动模型"用 L.S.0 是最自然的调用方式，工具没有任何拦截或自动降级。
- 修复建议：check 模式 l_s=0 时自动剥离 ACTA（或自动改 L.S.1 并在摘要注明），至少在参数校验层给出明确指引。

**#9【P2】SADI/SAME 重放在元素改判后致 SHELXL 致命失败，set_restraints 无类型校验**
- 现象：t3 L195 设置的 P1–C22 / C22–C25 混型 SADI + SIMU 在 L199 run_shelxl(adopt) 正常通过；L226 将 N4–N7 改判为 C、L230 再次 add 同一组 restraints 后，L234 run_shelxl 因连串 `SAME/SADI sfac type mismatch` 报 job.res 为空，agent 只能 L243 checkout 回滚。
- 根因猜测：restraint 存储在改判/重加后重放出重复或错位条目；set_restraints 不校验混型 SADI，错误只在 SHELXL 运行期爆炸。
- 修复建议：set_restraints 落库时做 sfac 一致性 lint（警告级）；重放前去重；SHELXL 仅警告未产出结果时把警告全文回传（现已做到，保持）。

**#10【P1，战役中已修】change_space_group 拒绝主动降群，假设检验被堵死一整轮**
- 现象：p780-t1 数据侧有 29/111 条 c-滑移消光违例（L279 消息），按纪律需要 C2 对照；L287 `change_space_group("C 1 2 1")` 被拒："actual symmetry closes to C 1 2/c 1 ... use the suggestion from check_symmetry"。t1 只能把违例列为未解决交付；整个 p780-t2 任务就是"按更新后的降群流程重做完整 C2 分支"（t2 L3/L16 消息，"执行修复后的真实降群"，L37 降群成功、C2 下重合并 1648 独立反射）。
- 根因猜测：工具把"内容实际对称性"当硬门，没有 deliberate-subgroup 通道。
- 修复建议：已修；建议补一条回归测试：C2/c→C2 降群+重合并+反演相关性审计全链路。

**#11【P1】refine(mode=anisotropic) 把新加自由 H 也各向异性化，且 iso/aniso 补救调用表现为无效果**
- 现象：p780-t1 加入 μ-OH 的 H3X 后，L155 aniso 精修把 H 卷入各向异性（L172 消息"节点工具对新加 H 的一次各向异性标记不合常规"）；L159 `mode=isotropic`（label "reset_added_H_to_isotropic"）与 L163 aniso 恢复，三次调用摘要完全相同（r1_strong=0.0612/84 参数），未见状态改变；agent 最终放弃，从更早节点 n0012 开 SHELXL 分支接管（L176）。
- 根因猜测：aniso 模式无元素豁免；iso/aniso 转换对 H 的 use_u_aniso 翻转没生效或摘要未反映。
- 修复建议：mode=anisotropic 默认豁免 H（或加 exclude_h 参数，默认 true）；转换类操作在摘要中回显每类原子的 iso/aniso 计数。

**#12【P1】权重状态分裂：refine(weight_a,b) 只在单次调用生效，SHELXL 永远读会话旧 WGHT**
- 现象：t2 L466 消息："`refine(weight_a,b)` 只在该次 smtbx 调用生效，后续 SHELXL 仍读会话保存的旧 WGHT，所以刚才并未真正测试推荐值；optimize_weights 又因 GooF 已为 1 而保留旧值"。SHELXL 推荐权重闭环（PLAT965）在平台内无路可走，agent 被迫复制 job.res、手改 WGHT、经 ingest_vendor_data 收回（t2 L470/L474/L488 命令）。
- 根因猜测：权重存在会话级单一状态，refine 参数不落会话；optimize_weights 目标函数只看 GooF 容差，不支持"采纳外部推荐值"。
- 修复建议：refine 的 weight 参数写回会话（或加 persist 开关）；提供 set_weights 工具或 optimize_weights(seed_from='shelxl_recommendation')。

**#13【P1】长驻会话缓存 context.json，元数据更新对输出链不可见，逼出"手改 final.cif"**
- 现象：t3 第 8 轮用户已把 SAINT 晶胞测定元数据回填 context.json（L1504 用户消息），write_outputs 生成的 CIF `_cell_measurement_*` 仍是 `?`（L1517 消息）；诊断为"长驻精修会话缓存了旧版 context.json，checkout 不会刷新实验元数据"（L1540 消息）；agent 只能直接补写 final.cif 并重跑 checkCIF（平台纪律本来禁止手改 CIF），REPORT.json 也同样残留旧占位符需手工同步（L1567 消息）。
- 修复建议：write_outputs 每次从磁盘重读 context.json；或提供 refresh_context 工具。

**#14【P1】HKLF5 数据接入无 setting/一致性护栏，naive 用法产出貌似合理的垃圾**
- 现象：t2 首次 HKLF5 导入把模型末尾留成 `HKLF 4`，SHELXL 把双畴行当普通反射，R1≈0.65（L138 消息）；补上 BASF/HKLF5 后 BASF 收敛到 0.517 但 R1≈0.62、原子发散，0.517 完全是伪畴比例（L157 消息）；真正根因是 HKLF5 与 HKLF4 不同 setting，需 `(h5,k5,l5)=(-h4,-k4,h4+k4+l4)` 变换（L178 消息），由 agent 自写脚本最小二乘反推。t1 同期也独立踩了 setting 混用（t1 L354 消息"此前 0.62 的结果确属 setting 混用"）。
- 根因猜测：ingest 不检查 HKLF 码与数据文件批次结构的匹配，也不做主畴与当前数据集的指数相关性/变换检测。
- 修复建议：ingest HKLF5 时自动置 HKLF 5+BASF；新增"HKLF5 对 HKLF4 主畴配对审计"工具（指数重合率、相关系数、最优整基变换），把 t2 手写的 derive_hkl_transform.py 产品化。

**#15【P1】新原子标签生命周期不透明：工具报的标签立即失效、约束可登记到不存在的原子**
- 现象（t3 第 7 轮连环）：峰表统一修复后 add_atoms 成功加 H 并报标签 `H107X`（L1232 消息）；节点提交自动规范化改名，显式 rename_atoms("H107X"→"H53") 失败 `labels not in model`（L1236）；agent 预判会改成 H53 并为 H53 登记 DFIX "成功"（L1241 消息），实际标签是 `H0`，该 DFIX 在精修时被静默跳过（L1248 消息），需删除重建。另 t2 L334：model_disorder 无法为 SHELXT 风格标签 C014 派生 B 部件标签，要求先 rename，同属标签空间/规范化不闭环。
- 修复建议：工具返回的标签必须是提交后终值；set_restraints 校验原子存在性，未知标签直接拒绝。
- 已知关联：>4 字符标签失步（已修的是写出失步）；此处是"返回值失步+约束校验缺失"两个新面。

**#16【P2】assemble_asu 把"无事可做/合法独立客体"报成失败**
- 现象：t1 L569、t3 L329 均为 `assembly did not reduce detached atoms (12 -> 12); model left unchanged` ok=false；两处的 detached 都是晶格苯（合法独立客体，t1 L574 消息、t3 L1043 消息确认验证器所报 detached 即苯双取向）。
- 修复建议：区分三态返回：已连贯 / 已改进 / 无法改进（附独立片段识别结果），只有异常才 ok=false。

**#17【P2】add_hydrogens 分类阈值被热运动拉长键欺骗**
- 现象：t2 L91 消息：晶格苯 C43 因运动拉长的 1.52 Å 键被判成 CH₂，将生成化学不可能的 C₆H₇；agent 用更宽容的 sp² 判据重建。与已知键长门家族相邻，但这是"过长 C–C 误增配位"的反向新样例。
- 修复建议：H 分类综合环检测/平面性，不单看键长窗。

**#18【P2】canonical 重命名的第二连带：8 个有序 C 误继承无序占有率**
- 现象：t3 L680 消息：第二轮 canonical 重标号后 C12/C18/C21/C24/C26/C27/C29/C35 八个满占有率有序原子错误继承了无序占有率，占有率加权 H 总数偏离 68；agent 逐个恢复 1.0。已知 #10（rename 不联动 disorder_groups.members，t3 L480 消息）之外的独立损伤面：占有率字段也会错挂。
- 修复建议：rename/canonicalize 的联动修复应覆盖 occupancy/FVAR 绑定，不止 members 表；补回归测试。

**#19【P2】修复部署与声明不符（修复验证缺口）**
- 现象：第 4 轮部署说明称金属键连过滤已修，实测 `include_metal_bonded=true` 仍把 La···C 3.18–3.32 Å 送进共价半径异常键门并连坐误拒 C7，干净重加氢只得 103 H（t3 L913 消息，"与本轮已部署说明不符"）；C7 的 `secondary_xh2_sites bad connectivity` 直到第 5 轮仍原样复现并触发纪律停轮（t3 L1151/L1152），第 6 轮 π/σ 剪除部署后才通过（L1154 用户消息、L1167）。
- 修复建议：每项引擎修复附带用当轮失败样例做的最小复现测试，部署前跑一遍（transcript 里的失败节点都留了，可直接做回归夹具）。

**#20【P2】诊断信息不可信：checkout 陈旧提示、adopt 摘要计数与节点不符**
- 现象：checkout 提示"in-process refine treats H as free atoms"，实测 C–H 距离严格保持 0.97/0.93 Å，判定为陈旧提示（t3 L1167/L1172 消息）；第 4 轮 adopt 摘要声称收回 180 原子，活动节点实际 174（t3 L980 消息）。agent 为此多花位移审计与逐标签 diff。
- 修复建议：摘要计数一律从提交后节点重新统计；移除/更新陈旧提示。

**#21【P2】峰缓存生命周期：checkout/节点操作后峰表清空，靠报错兜底**
- 现象：t3 L1003/L1011 `no stored difference-map peaks - refine first`（第 4 轮，峰表统一修复前）；修复前 inspect_map 的扩展峰（40 个）不进 add_atoms 候选池（只认 refine 存的前 8 峰），两种正式加入方式返回 ok=true 且 added=[]（t3 L1030/L1187 消息）。已知 #13/#14 家族，新细节是"ok=true+空结果"的静默语义（见第 5 节）。

**#22【P2】validate_structure 口径与 PART 感知几何不一致**
- 现象：t3 L1307 消息：验证器按严格 σ 键口径报 La 配位数告警且把 H0 近接触计入，与 PART 感知配位表不同口径，需在 VALIDATION 里人工解释；p780-t1 L303 对 Al 报 `CN=10 outside [4,6]` 但列出的邻居是 8 个 O（六配位 Al 的桥连计重）。
- 修复建议：金属 CN 告警采用与 get_geometry 相同的连接判定，并在消息中列出计数口径。

**#23【P2】schema/参数命名摩擦**
- 现象：refine 枚举须写全 `isotropic`（p780-t2 L28 `'iso' is not one of [...]`）；compare_nodes 参数是 `a/b`，agent 直觉传 `node_a/node_b` 被拒（p780-t2 L67）。
- 修复建议：接受常见别名或统一命名（node_a/node_b 更自明）。

**#24【P2】get_project_brief 输出无上限，超长被界面截断后重试 4 次**
- 现象：t3 L435 消息"项目摘要返回过长被界面截断"；L434–L441 连续 4 次 get_project_brief。
- 修复建议：brief 分页/摘要化，节点列表超阈值折叠。

**#25【P2】MCP resources/list 未实现**
- 现象：每个会话开头 list_mcp_resources / list_mcp_resource_templates 失败或返回空（t3 L6/L7 `Method not found`；p780-t1 L5/L7、p780-t2 L6/L7）。纯噪音但每次都消耗一轮调用与审批。

---

## 3. shell 绕道清单（工具能力缺口信号）

1. **结构求解整段在工具链外**：内置粗解只有电荷翻转。t1 CF 15 次全败后（L30 消息），agent 依次：shell 跑 `crystalpilot.cli solve`（L29）→ 搜盘找 shelxt/shelxs/olex2 未果（L34/L38/L42，含 1 次超时）→ 自写 `cf_rescue.py` 扩窗扫描（L67 超时后读 events.jsonl 兜底）→ 自写 `patterson_heavy_atoms.py`（L82/L90 两次崩溃后成功）与 `heavy_atom_search.py`（L130 崩溃，flex API 误用）→ 160 候选定量筛选出 La 种子（L139 消息）。**缺口：无 Patterson/重原子工具、无 SHELXT 集成、CF 无备选参数策略**。
2. **SHELXT 靠裸 shell 运行**：t2 在 `vendor/shelx/shelxt.exe` 直接跑两次（L35/L39，LATT±1 对照），结果经 ingest 收回。SHELXT 其实就在本仓 vendor 目录，t1 的搜索却因递归超时+rg 引号问题没找到（也可能当时尚未放入，transcript 无法区分）。**缺口：求解器发现与封装**。
3. **HKLF5/HKLF4 基变换全程手工**：t1 `derive_hklf5_twin_law.py`（L298/L306），t2 `derive_hkl_transform.py`（配对+最小二乘变换矩阵）与 `transform_model_to_hklf5_setting.py`（L194/L234，cctbx 变换晶胞/坐标/ADP）。**缺口：见问题 #14**。
4. **刚体无序第二取向拟合**：t2 `fit_benzene_minor_orientation.py`（L357），model_disorder 只支持 ADP 主轴拆分或逐原子 second_sites，无"整环刚体旋转/平移生成第二取向"，agent 在外面拟合好坐标再喂 second_sites。
5. **SHELXL 推荐权重闭环**：t2 复制 job.res→手改 WGHT→ingest_vendor_data 收回（L470/L474/L488）。见问题 #12。
6. **氢完整性审计成为常驻外挂**：t1 `hydrogen_completion_plan.py`（4 次），t3 `audit_hydrogen_mapping.py`（约 10 次，L554–L912 区间），逐载体列"应有/已加/被跳过原因"。**缺口：add_hydrogens 无 dry-run/审计模式输出逐载体判定依据**。
7. **交付物一致性审计外挂**：t3 `round4_map_audit.py`、`round4_output_audit.py`（3 次）、`round7_output_audit.py`（3 次），逐标签核对 CIF/RES 的原子数、H 数、PART-H、FVAR。存在原因即问题 #3/#20（工具摘要不可信，"避免沿用工具摘要中的任何歧义"，t3 L1066 消息）。
8. **发表参照映射**：t3 `map_published_disorder.py`（L47）把 COD 7135354 经整基变换映射回当前 setting 提出 PART 候选。属合理科研脚本，但"与参考结构做基变换对齐比较"可考虑产品化。
9. **消光违例子集检验**：p780-t2 `analyze_c_glide.py`（3 次），对原 c-滑移禁戒类反射单独算 Fo²/Fc² 拟合质量（子集 R1=0.432 的关键否定证据）。**缺口：audit_reflection_data 不支持按消光类/自定义子集切片**。
10. **agent 现场读平台源码自诊断**：t3 L73–L95（rg "cannot read element"、读 nodes.py/tools_extra.py）、p780-t1 L70/L165/L305（读 tools_analysis.py、shelx_writer.py 查 Z 处理）。工具报错信息不足以定位时，agent 把源码当文档用，本身无害，但说明错误信息可操作性不足。
11. **手改交付 CIF**（例外性质）：t3 第 8 轮因 #13 缓存问题直接补写 final.cif 元数据五项（L1540 消息之后），并同步 REPORT.json，平台纪律本禁止，属被迫破例。

（此外 351 条 shell 中的大多数是只读核查：Get-Content .res/.lst/节点 json、Select-String WGHT/FVAR、备份 Copy-Item，这类"读会话内部文件"的高频需求本身提示：节点/作业工件缺一个类型化只读查询工具。）

---

## 4. 低效模式清单

1. **求解阶段 28 分钟无果重试**（t1 14:06→14:34，L18–L196）：CF 15 次失败→扩窗扫描顶到工具 5 分钟上限自动终止（L70 消息）→5 个自写脚本 6 轮崩溃-修复。用户最终另起 t2 救场（14:31），两条线重复解同一结构、各交付一份成品。
2. **optimize_weights 长跑无心跳**：4 次超过 2 分钟（t3 L777=483s、L968=302s、L1198=295s、L1281=157s），期间 agent 连发 10+ 条"仍在运行/不敢打断"消息（L772–776、L965–967、L1195–1197）。需要进度事件或分阶段返回。
3. **spoof-restore 三明治成为标准工作流**：t3 第 2–3 轮每次 add_hydrogens 前后都要 La/Ni→Si 改判 + P1/P2 挪 0.19–0.22 Å、加完氢再复原，共约 12 组 edit_atoms 对（L251–L794 区间：L251/259、L288/296、L342/350、L358/366、L509/525、L535、L609/617、L629/637、L645/653、L688/696、L700/708、L735/743、L747/755、L786/794）。每组多花 2–3 次调用，节点链膨胀，且 agent 自己披露会带来 H 朝向的小系统误差（L605 消息）。第 4 轮起被禁止后改为披露缺陷。
4. **FVAR 自洽马拉松**（t3 第 7 轮，L1364–L1466）：为让 CIF/RES 数值一致，20+20+50+100 周期 SHELXL、每段后 1 周期探针验证漂移、3 次 edit_atoms 手工回写 H0 坐标/Uiso。一半是真实占有率相关性，一半是问题 #3 的装配缺陷税。
5. **同一 L.S.0+ACTA 坑跨任务踩 5 次**（问题 #8）：每次浪费一个 run_shelxl+一轮诊断；无工具侧记忆/护栏。
6. **PowerShell 引号/glob 摩擦**：约 8–10 条命令纯因转义失败重写（t1 L371 解析错误、t3 L89 rg 正则被引号拆碎、p780-t1 L165 `tools*` glob 不展开报 os error 123 等）。harness 的 `powershell -Command '...'` 嵌套引号方案对复杂命令极不友好。
7. **get_project_brief 截断重试 ×4**（问题 #24）。
8. **审批风暴**：5 个 task 共 625 次 approval_request/decision（t1 一个 task 120 次），全部人工/策略 accept、零拒绝，审批粒度显著高于风险粒度，纯时延成本（t1 L7 请求到 L9 决定间隔约 12 分钟，说明确有人在点）。

---

## 5. "静默错误"专节（ok/成功表象下的错误：最危险级）

按危险度排序，均有出处：

1. **write_outputs 静默复用失效 job**：run_shelxl(L.S.0) 失败后写出器复用上一份 20 周期 job，交付物 CIF/RES 不一致且无任何警告（t3 L1084 消息）。若非 agent 自写审计脚本比对，会以不一致文件交付。
2. **CIF/RES FVAR/PART-H 失同步**（问题 #3）：多轮 write_outputs 全部 ok=true，实际 RES 只有 46 个非零 PART H、CIF 106 H（t3 L1105）；第 7 轮修后仍复现一次（L1325）。
3. **import ok=true 但 0 原子/错空间群**：p780-t1 L56（带 hkl_path），摘要里 `imported_atoms: 0` + `P -1` 是唯一线索。
4. **起模指针回零原子模型**：solve/import 全绿，reload 后模型为空（t1 L174、t2 L249 消息），两个战役独立复现。
5. **branch/checkout 静默重放旧氢约束**：命名分支后 H66 被还原成 H55，非氢模型不变、无任何警告（t1 L574 消息）；同类 adopt 丢 H 属已知 #12，但 branch/checkout 触发面当时未知。
6. **adopt 摘要计数说谎**：摘要称 180 原子、节点实际 174（t3 L980 消息）；修复后改为显式 `h_replay_lost` 清单（L1290 消息），是正确方向的对照样板。
7. **加峰工具 ok=true + added=[]**：两种正式加入方式（索引/距离窗）都返回成功空集，密度证据明明达标（t3 L1030、L1187 消息），"成功地什么都没做"，若 agent 不数原子数就会以为 H 已加入。
8. **refine 权重参数静默不落会话**：推荐 WGHT "测试"实际没发生，SHELXL 读旧值（t2 L466 消息）；optimize_weights 又"成功地"保持旧权重，PLAT965 于是永不消失。
9. **HKLF5 naive 接入产出伪 BASF=0.517**（t2 L157 消息）：所有调用 ok，数字看起来像真实畴比例，实为 setting 混用垃圾。孪晶新手极易采信。
10. **粗解 CIF Z=1 语义错误**：不纠正则最终 CIF 公式/密度/F(000) 全错，而全链路无告警（p780-t1 L310 消息）。
11. **checkout 陈旧"H 为自由原子"提示**（反向静默：假告警）：迫使 agent 用位移审计自证约束生效（t3 L1167/L1172 消息）。
12. **DFIX 登记到不存在标签**：set_restraints ok，精修时静默跳过（t3 L1241/L1248 消息，问题 #15）。
13. **并发场景下所有单次调用都"ok"**：t1 的 run_shelxl 返回 ok=true + R1=0.687（L251），数据文件被换是外因，但工具没有校验"本 job 所用反射文件=节点绑定文件"，把环境损坏当模型结果原样返回。

共性教训：**摘要计数（原子/H/PART）与"实际提交后节点状态"必须同源；imported/added/replayed 为 0 或有丢失时默认 fail 或显式警告清单**。第 7 轮 `h_replay_lost` 的做法应推广为所有改模工具的标准返回字段。

---

## 附：本审计的方法与局限

- 解析全部 5 份 transcript.jsonl（共 3559 行事件），穷举 `ok=false`/`status=failed`（34 例全列于第 1 节）、全部 351 条 shell 命令、全部 202 条 agent_message；关键结论均回读上下文事件核实。
- 行号为 jsonl 物理行号；时间戳换算为本地时刻。
- "SHELXT 是否在 t1 期间已存在于 vendor/"无法从记录判定（t1 搜索失败可能因超时/引号，也可能当时确无），已如实标注。
- p780-t1 的粗解命令内联在 L50 备份命令中（输出目录 runs/run_c12afabd86 于 L52 起被读取），未单独成行。
