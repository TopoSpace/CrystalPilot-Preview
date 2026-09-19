# 第二轮实施：结构检查器、安静动效与可信执行

> 从 `d0771aa` 继续实施 `PLAN-2026-09-07-upgrade.md`。开始于 2026-09-07 夜，验证延续至 09-08。以下区分已落地、真实实验和仍有限制的部分；不是宣称整份多年演进路线图已全部完成。

## 1. 范围与纪律

- 用户要求后，原四个 Sol 维护子会话已停止/归档；未提交代码先保存 patch/zip，再由四个 **GPT-6 Astra / xhigh** 会话重新检查与完成。后续维护审查也使用 Astra，未提高到 max。
- 产品内实验仍使用 **gateway/crystalpilot → GPT-5.6 Sol → xhigh**，子代理关闭；未调用 OpenRouter 模型。两家提供方及用户自行配置的密钥保留，密钥不回显、不入 Git。
- 只改隔离 worktree；没有读写 `H:\CrystalPilot` 主检出或个人 Coding Codex。科学项目放在 `H:\CrystalPilot-campaigns\upgrade-20260907`，输入来自已记录的外部原始数据或当前仓库公开样本，原始源文件不改。
- 8010 在无活动模型回合时分批重启，UI 和对应后端一起验收；不按进程名杀其他进程，不把测试数据、依赖二进制或全部日志塞进 Git。

## 2. 结构与分析真正联动

主提交 `2a73bf3`。

- 分析行可以打开紧凑检查器，并定位**真实对应的原子/对称像**；使用 canonical row、绝对对称操作和当前 scene 实例，不按标签随便跳到 ASU。
- 当前范围没有对应实例时明确说明；改变范围或节点后重新判断，过期选择不冒充当前选择。引用仍带原节点、对称操作和实际数值。
- 结构在分析时保持可见，结构/表格比例可调；低优先级判据按需展开，减少文字和边框堆叠。
- 引用按钮对触摸/键盘可达；结构标题不再嵌套交互元素，窄窗控制换行/收敛。
- 修复 packed/grown 范围中只包含部分 identity 实例时，标题误把其元素计数当完整 ASU 化学式的问题。能确认完整 ASU 才显示完整组成，否则显示模型 ASU 原子数。

**边界**：当前高亮一个可确认的端点，不是整个环/整条关系的双端点高亮。某些 π 环质心行没有服务端原子映射，检查器明确显示质心/线段信息，不猜环中原子。同步双结构比较、完整 Cage/200% 缩放矩阵仍在后续。

真实 ZIF-8 验收包括 `N1(-z+3/2,y-1/2,-x+1/2)` 的精确实例、对应引用，以及收回 ASU 后拒绝错误替代。父级七项真实浏览器测试通过，覆盖六种配色/窗口组合；子会话另对 MOF-5、NU-1000 的手机/桌面进行了真实 API 验证。

## 3. 动效和会话状态不再互相矛盾

主提交 `df148da`，审查补丁 `af7c7b9`。

- 同时只有一个主工作标记；去掉尾部重复 shimmer 和各卡重复 spinner。等待回答、断线、审批、工作和终止是不同状态。
- 中断的工具/命令明确“未完成”，保留原始状态、错误和部分输出，不制造成功、指标或提交节点；新回合不再复用上回合残留的 running 卡作为当前动作。
- 错误、问题、插话不会被完成摘要吞掉。折叠时保留键盘焦点与细节开合，阅读历史时新消息不强拉到底部。
- shared motion 订阅同时控制 JS 滚动、计时、CSS 和 3Dmol：减少动效时即时跳转；页面隐藏时暂停旋转/动画和不必要时钟刷新，恢复时安全继续。
- 居中改为可取消的约 300ms 过渡，隐藏、减少动效、卸载或手动拖动会终止；不改晶体几何或科学深度设置。

### 用户指出的“就绪（？个工具）”

真实原始事件只有 server/status/error/thread/ts/eid，没有 n_tools；同一次启动收到两条 ready，间隔约 0.2 秒。修复为按服务器/线程启动周期合并，未知数量省略，显式数量保留；新的 starting/failed/restart 可重新开始周期，不硬编码 74。

Cage 真实转录保留了两条 ready，但 8010 浏览器只显示一次“晶体学工具已就绪”，没有 ASCII 或中文问号占位；不是字体替换。

### 独立审查发现的两条边界

1. 旧页插入会重编号 reducer 的局部 ID，聚焦 reasoning 可能误绑定历史失败命令，导致失败被藏。现保存持久 source eid，并以源身份/类型/顺序重新匹配；无唯一安全匹配时退出 pin，不强制类型转换。
2. `zoomTo(..., 0)` 会重置 slab；若首个动画帧前取消，旧实现来不及恢复深度。现恢复 from 视角后立刻重施深度并安排受保护重绘，每帧恢复也保留。

回归先复现了原问题，再验证修复。真实 3Dmol 首帧取消用例在子会话 Vite 中观察公共 API；生产静态包不开放测试探针，该专门探针用例会明确跳过，不包装成生产环境已完整测量。

## 4. checkCIF：修复真实阻塞，不是调高超时

主提交 `6b3bcda`。

原 NU-1000 在 90 秒和 420 秒都不生成 `.chk`。失败日志有实际证据：SHELXL executable 路径被旧程序截断。仅相对 SHLEXE、仅 8.3 别名或仅复制 PLATON 不能解决；短的物理 SHELXL 路径置于 PATH 前端成功，短路径中包含空格也可以。因此不是“所有空格都不支持”。额外构造的 253 字符 job cwd 还复现了旧程序文件 I/O 挂起。

最终把输入/sidecars/SHELXL 与所需 DLL 放入受控短 runtime，保留原 PLATON 只读执行文件；输出诊断复制回原 job。Windows Job Object 在子进程恢复执行前接管其进程树，按拥有的进程/句柄清理，不杀同名外部程序。

成功门槛改为：完整 PLATON header、分级 summary 数量对账、完成标记、文件稳定；不是“文件大小暂时没变”就当成功。schema v2 记录 attempt、execution/report status、退出码、时限、清理状态、诊断路径和来源。超时、失败、取消的 counts 为 null，保留原始部分文件，旧成功不能替代最新失败。

验证产物另有短临界区锁，防止晚到旧结果覆盖新失败；先捕获节点/来源再加 artifact 锁，不形成 artifact→project 反向加锁。最简节点检查的元数据警报也不再直接豁免。

| 父级实际调用 | 时间 | A / B / C / G | 含义 |
|---|---:|---|---|
| 同一 NU-1000 诊断交付 | 17.438 秒 | 19 / 10 / 41 / 19 | 执行已恢复，结构/元数据仍有警报，不是科学通过 |
| Sol 小分子第二轮交付 | 4.750 秒 | 8 / 3 / 9 / 8 | 报告和来源可读，仍待逐条解释及人工信息 |

原始输入和旧失败 job 未覆盖。子会话还真实验证了成功之后的一秒超时：新报告 counts=null、原成功 job 保留，owned 进程树和短目录清理完成。不同 sidecar 控制组 C40 与 C41 的差别如实记录，没有固定或人为改警报数。

## 5. R1 后端第一单元

主提交 `5700663`。这是**合作进程间的一致性基础**，不是全系统 ACID 声明。

- stdlib msvcrt/flock 稳定 OS 锁，加规范路径对应的进程内 RLock。整个 invocation 持锁；不同 NodeStore 实例的同线程嵌套不死锁；不删除/抢占别人的锁。
- 直接 NodeStore commit/branch/set_active 也受保护；单节点先暂存完整文件再发布，通过 publication marker 恢复“目录已改名、state 尚未提交”等中断边界。
- 显式 `expected_node` / `expected_project_revision` 可拒绝过期请求；project revision 与原 node revision 分开，能够检测 checkout ABA。旧调用省略前提时自动重载旧 handle，不把旧模型悄悄挂到新 head。
- 成功的独立诊断子节点保留；外层失败报告 partial 和 retained nodes，清理未发布脏 session。取消之后不再为清理启动新的掩膜重算。
- 失败换数据先完整解析/merge 预检，有限 undo 保护已声明的 HKL/context/start 输入；独立子提交后推进 undo 基线，不把成功状态回滚成更早输入。
- 会被写工具消费的峰表、investigation 变化推进 project revision；纯只读提示不变、不制造模型节点。

真实 spawn 覆盖两个 MCP ProjectHandle 并写、直接 NodeStore 并写、读锁挡写、超时/取消、锁持有进程退出、节点发布两侧的崩溃恢复、ABA、失败 swap 等。父级第一组 62 通过，跨 checkCIF/import/refinement 的组合 237 通过、1 个缺 fixture 跳过。

**明确边界**：长读仍阻塞写，不是并行不可变数据快照；未提供 expected token 的旧上游审批不自动获得语义绑定；没有完整历史 HKL 版本、跨所有输入文件的硬崩溃事务或 call-ID 幂等。旧二进制不遵守新锁，发布必须让合作写进程同版本；回滚前先用新版本完成 pending publication 恢复。

最终检查又发现可选 `consult_specialist` 的父调用持锁、子 MCP 打开同项目的互等问题，已用独立补丁 `803479d` 修复：父锁下复制必要的固定节点/当前输入到独立快照项目，顾问只获取快照锁；不复制凭据、原工作台状态或整份历史/地图缓存。明确继承项目保存的 model/provider/effort，并关闭 native multi_agent 和顾问递归。

顾问默认预算 180 秒、范围 1–900，最多 2 秒清理宽限；超时/取消后晚到结果不能发布 verdict，SDK 未完全关闭时明确 `cleanup_pending`，不谎称远端已停止。队列等待不冒充执行耗时。117 项父级回归全部通过，其中真实 spawn 子句柄在父原锁仍持有时可读独立快照、写被拒，主项目文件字节不变；harness/model部分为明确 fake，不计作真实子代理收益试验。

此顾问快照仅支持当前 active/latest 的反射输入，历史匹配数据未知时拒绝；纯 CIF 可做几何快照。没有上游瞬时 turn 参数通道时只继承已保存项目 override，明确 `parent_turn_overrides_known=False`；不是完整历史数据版本或子代理收益证明。

## 6. 前后端数字与数据来源

### SHELXL 计数

主提交 `aaa7d0c`：不再把参数数硬编码为 −1、不再把 strong reflection 数当作总反射数。优先读取本作业 ACTA CIF 的真实计数，RES 可提供总数据数；缺失时保持未知。

真实蔗糖控制：新节点保存 **240 个参数 / 16,720 条反射**，与作业 CIF 一致；strong 子集为 10,732，不能混用。零周期作业可能不生成 ACTA CIF，因此没有数据来源时不编造参数数。已有历史节点没有被追改。

### 导入比较条件

主提交 `3581bc3`。同一蔗糖模型：

| 观测来源 | 零周期 R1 | 四轮 R1 |
|---|---:|---:|
| CIF 中的原始 embedded HKL | 0.0411 | 本控制不需要 |
| 显式传入发表 SF-CIF | 0.6148 | 0.0412 |

这是“几何导入”和“精修条件/数据尺度等价”不能混同的实际反例；没有改原始观测去追数值。导入工具现明确提示比较前要对齐数据、尺度、权重、H 和掩膜条件。铜 BTC 配位聚合物 COD 2206821 的四轮 R1 为 0.0244，参考 0.023；不把该样本误称为 HKUST-1 已知答案。

## 7. 真实 Sol 多轮工作流

### 小分子：从空模到有界精修

源为记录过的仓库外 d0，只复制 HKL/INS，没有把参考坐标/最终式交给模型。gateway Sol/xhigh，subagents off。

- 第一科学回合 275.858 秒、15 次 MCP：空模→SHELXT→各向异性初模 `n0002`，R1 0.0656、wR2 0.2215、GooF 2.158。一次“重新导入本项目自身 HKL”被工具正确拒绝，模型随后改走定群/求解，没有写坏输入。
- 第二回合 137.733 秒、8 次 MCP：加入 11 个骑乘 H 并真正 adopt SHELXL，`n0004`、24 原子，R1 0.0381、wR2 0.1300、GooF 1.204。节点与生成 CIF 逐项一致；无删反射/删原子/新增 restraint。
- 第二轮输出在新子目录 `h-refinement-01`，保留第一轮。CIF/FCF/RES 为 provisional；不是发表级结论。未确认的 H 扭转、局部无序、异常反射和元数据继续记录。
- 第三回合 94.975 秒，通过真正的 `run_checkcif` 检查交付 CIF（该工具 4.776 秒），报告来源 n0004 / 模型修订 5 / 交付修订 1，A8/B3/C9/G8。UTF-8 的 VALIDATION.md 共 5585 字符，逐条解释保留；仍为 provisional、没有改模型或 finalize。普通报告读写不计为晶体学计算。

[小分子真实线程](http://127.0.0.1:8010/thread/01a07c8e-1be3-7913-8356-7c36f7477fac?project=H%3A%5CCrystalPilot-campaigns%5Cupgrade-20260907%5Csol-small-cold)

### Cage：先问必要事实，而非猜金属

只复制外部 d1 的 HKL/INS，记录并移除派生 INS 中四个零坐标/零 ADP 占位行，原始 INS 保存在 inputs。没有参考坐标或可信金属/配体信息，初始 P21/c 只当假设。

新后端上，正常首条消息启动（没有人为的“只回复就绪”模型预热回合），Sol 在 73.003 秒内完成 7 次真实工具调用：数据质量、有效分辨率、空间群筛选与 investigation。建议工作分辨率约 0.996 Å，P21/c 仍有强消光违例、未确认；没有运行 SHELXT/精修/掩膜，也没有伪造原子模型。

模型主动用真实 `ask` 卡询问金属元素和主要配体，没有把我们从历史审计知道的参考元素偷喂进去。初始浏览器验证了问题卡、question 状态和去重 readiness，没有合成这张卡。

随后**用户在 8010 中实际回答并提供 Zr**，系统作为用户先验记录而非衍射确认；配体仍未知。它在原 12 次总调用预算内做唯一一次 SHELXT：约 121 秒完成 24 次尝试，最佳 CFOM 0.6327 未达到既定 0.65 接收线，没有生成原子模型。系统未降低阈值、未追加同条件搜索、未精修/掩膜/定稿，活动节点仍为空模 n0000。这个失败是如实保留的真实瓶颈，不是“解析成功”。

实际互动还暴露出“可提供→仅提供金属→具体是什么”的能力确认绕路。新 full 指令 v42 要求开放事实直接问具体值、允许空 options 的自由输入，并区分未提供与不存在；70 项模板/版本/预算测试通过。该规则是指导，不夸大成能形式化保证模型永不多问。

因为用户确实回答了问题，后续浏览器测试不再假设问答永远停在未回答态；检查历史问题保留、当前 idle/question 与真实最新消息相符，不重置用户会话或补造问题。

[Cage 真实线程与问题卡](http://127.0.0.1:8010/thread/01a07cda-f6bc-7792-9450-5a9d3d08178b?project=H%3A%5CCrystalPilot-campaigns%5Cupgrade-20260907%5Csol-cage-cold)

## 8. 测试与证据口径

各组相互重叠，不叠加成夸大的独立测试总数。

- 全部现有 UI Vitest：**47 文件 / 499 项通过**。
- 组合后端：**237 passed / 1 skipped**；包含明确 opt-in 的真实 NU 二进制 checkCIF。
- 最终生产浏览器组合：**30 passed / 1 skipped**；跳过项是需要 Vite 公共实例观察器的首帧取消测试，已在子会话真实 3Dmol/Vite 下通过，不冒充生产静态包测试。
- 真实分析检查器：父级 **7 项通过**；真实工作流（Cage 历史问题/实际回答/启动和小分子警报侧栏）另 **2 项通过**，也包含在上述组合中。
- 动效/生命周期：真实只读回放与真实 3Dmol，加上明确标记的合成终止/聚焦/分页/visibility 情景。OS 最小化并非全部被实际测量，不把模拟 visibilitychange 包装成系统级认证。
- provider 额外边界 `13ff8e6`：代理提供方的附加 key 元信息请求不再跳到另一个官方主机，错误中的 URL 编码敏感值也脱敏；只有 dummy/拦截网络回归，不发送真实键。
- CIF-only 测试必须使用仓库外 basetemp。最初放进 workdir 被正确 guard 拒绝；改外部测试目录后相关 94 项及新 2 项回归通过，没有削弱项目隔离规则。

子会话 Vite/HMR 出现过原生 Windows 退出，后改静态构建透传服务完成实景检查；8010 未受这些子测试服务影响。不据此宣称生产界面发生同一崩溃或已经修复 Node 原生问题。现有 FastAPI 弃用和 3Dmol eval 构建警告保留。

精选截图/机器摘要在 `docs\evidence\2026-09-08`，完整本机记录在 `workdir\round2-*` 与对应外部项目；不包含密钥。

- [精确对称像与检查器](evidence/2026-09-08/inspector-real-symmetry.png)
- [390px 检查器](evidence/2026-09-08/inspector-390-kimi-dark.png)
- [深色分析布局](evidence/2026-09-08/inspector-1366-openai-dark.png)
- [真实会话层级](evidence/2026-09-08/conversation-real-replay.png)
- [Cage 首次真实问题卡](evidence/2026-09-08/cage-real-question-and-readiness.png)
- [用户回答后的历史问题保留](evidence/2026-09-08/cage-answered-history.png)
- [真实小分子验证侧栏](evidence/2026-09-08/small-real-checkcif-sidebar.png)

官方交互参照继续为 Claude Desktop 的分层视图/纠偏/面板、Claude Code 的 reduced-motion 和 Codex 的线程/审批/审阅边界，未复制品牌资产或宣称像素复刻。

## 9. 回滚与下一阶段

每个功能是独立提交，但按依赖成组回滚：恢复父级版本前先停相关写操作、完成 R1 pending publication 恢复；不要删除锁/marker 强行解锁。回滚 UI 后重建；认证修复和凭据格式兼容仍按 `PROVIDERS-2026-09-07.md` 管理。

本轮后续已完成受控反射数据版本、历史回放与逐指标可比性（§11–12），以及单视口前后切换（§10）。下一阶段仍需：审批时捕获版本、调用幂等、更多独立孔道/互锁反例、完整环/双端点高亮、同步双视口比较、子代理同模型同预算收益对照，以及更多原始帧/无序/孪晶真实样本。这些不在本次收尾中继续实施。Cage 的金属/配体事实需要人提供，不能靠更多工具或代理补造。

## 10. 结构前后比较：单视口 UI 切片

沿用节点树“对比”和结构“视图”浮层入口，临时比较栏展示固定两节点、前后切换与并列数值；不检出科学节点，不因后台出现新节点自动替换比较对象。退出恢复原查看/跟随意图及焦点。

- 保留同一个真实 3Dmol 视口。后端明确 frame compatible 才允许共用镜头；未知/不同坐标系分别保存镜头。不做坐标配准或旧式 ghost 叠加。**即便坐标系兼容，两侧原子选择仍独立**；没有后端明确身份映射，不凭同 label 推断同一原子。仅同节点重绘/返回时按 label、PART、绝对 symop 唯一恢复，缺失或不唯一保持未选。
- 接入只读 comparison DTO，R1/wR2/GooF 分别检查决策与实际节点/模型/数据/测量来源。未知、旧服务器缺接口、错误 pair 或沿用指标不产生改善箭头；普通有符号数值变化仍可中性显示。H、坐标、拟合尺度、权重变化不由客户端统一判为不可比。GooF 的颜色仍衡量距 1 的变化，不把每次下降都称作改善。
- 节点树“R1 最优”改为中性“R1 最低值”，明确未核对各节点条件；历史指标记录只连接已核对的最后一对，不把跨未知条件的连线当作改善趋势。
- 分开标示模型 ASU、scene 实例及实际显隐后的绘制数量。绘制计数复用 renderer 原有元素/PART/分数剖面过滤，不改变晶体内容；相机遮挡不改变计数。图层继续使用本侧 scene.range，保留原 atom/tile/质量预算和每胞量语义。未确认反射来源时不为比较请求或显示旧反射派生图层，仍可正常查看几何。
- 引用两节点各自的数值、数据/测量来源和条件状态，不把当前 active 节点冒充所选对象；请求核对历史来源仅预填输入框，不自动绑定或发送模型消息。

本切片本地验证：**139 项定向 Vitest、生产 build、15 项 Playwright 组合通过**。组合包含 11 项新比较测试（8 项真实节点/渲染/布局，3 项明确标注的合成条件、错误 pair、晚到响应场景），以及既有动效/首帧取消/深度/超胞覆盖回归 4 项。Vite 公共 API 观察用于实测单 canvas、镜头与 fit；截图不代替实际像素/选原子检查。五种窗宽为 390/900/1100/1366/1920，涵盖 13–16 字号、三套配色深浅与减少动效。既有 motion fixture 的模拟事件/visibility 边界不升级成 OS 级认证。

Astra 只读审查另发现两处遗漏，均先复现再修复：ASU→未缓存超胞曾将旧镜头误存入新范围 key；从基线退出曾在返回 scene 到达后丢掉恢复的选择。现镜头/可交互状态绑定**已完成的 scene 请求 key**，并保留 node-tagged 精确选择恢复；新真实 3Dmol fit 与 reducer 回归覆盖了原测试未覆盖的路径。

**集成边界**：上述 UI 子单元实景使用原有未绑定的小分子 n0002/n0004，验证几何、只读行为与 unknown 降级；不将它们追改成绑定数据。最终父级已在新外部项目完成版本绑定 pair、权重/反射范围变化的真实来源验收，并在生产 8010 运行 `CP_COMPARE_REQUIRE_BOUND=1` 的明确 n0003/n0001 对（见 §12）。合成 comparable response 不替代这道门槛。本 UI 单元不宣称双 WebGL 视口的完整生命周期已验收。

回滚该 UI 功能提交后重建前端即可；共享 DTO 为可选兼容字段，可保留。不得通过回滚 UI 删除数据版本、锁、marker 或更改科学 active 节点。
## 11. R1 后续有限单元：反射版本、历史回放与数值比较来源

后续于 `1184ff6` 的独立后端单元；不改变数值引擎，不把旧历史反射来源补造成已知。

- 新的受控导入/换数据保存 `.crystalpilot\refine\data\dNNNNNN` 不可变输入包；原始 HKL/CIF 来源字节保留，转换后的观测和转换尺度分别记录。普通模型编辑/精修/读取不生成新反射版本。原始观测版本与模型的波长、晶胞/群、HKLF、SHEL/OMIT、权重、孪晶、H、掩膜条件分开保存。
- 数据和完整节点先进入拥有明确 transaction ID 的暂存区；`state.json` 同一次替换提交 active model/data。崩溃在提交前保留 A，提交后保留 B 并完成受控兼容输入；alias 拷贝中途退出会保留 partial 并用新的 owned 文件重试。恢复已提交结果也推进 undo 基线；持续 I/O 阻塞明确报告已提交节点和 recovery_required，不假报“状态未变”。不扫描删除别人的目录，不删除永久锁。有限输入 journal 不是所有原始帧、外部文件或断电场景的 ACID 承诺。
- 节点保存实验上下文，实际 SHELXL TEMP/SIZE 指令与声明/人工补充的 experiment 分开记录。数据/节点切换恢复对应上下文，后补值另存在按 data revision 分组的 `working_experiments`，可由 brief 查看，不追改历史计算。真实追加对照确认蔗糖298 K→导入CuBTC293 K→返回蔗糖298 K，R1仍0.0411；后补310 K及明确清空均保留为当前记录，不伪装成历史条件。最新 chemistry/provider/其他用户设置不随之回滚。
- 普通交付工具的 output_dir 不可指向 data/nodes 档案；显式 checkCIF 档案路径须先导出副本，避免相邻 sidecar 写入。默认活动节点验证仍使用独立 job 目录，原有正常交付流程不变。
- 旧节点 `data_revision=null` 保持未知，打开/几何查看仍可用并明确 `binding_required`，不是假装纯 CIF 或丢失 HKL。使用 `swap_reflection_data(model_node=..., hkl=..., reason=...)` 显式给出匹配数据时创建新绑定子节点；原节点和旧指标不重写，新节点需要重新测量。提供数据是明确的用户配对声明，不等于自动证明从未保存过的历史对应关系。
- 历史节点的反射计算只读取其绑定版本。旧无来源 map/peak/void/data cache 不能借当前 HKL 冒充历史计算；有绑定才能重新生成，纯几何 CIF 能力不变。Map 使用节点实际测量的掩膜选择，而非仅因保留了备用 mask 就使用它；源记录说明 in-process merged/正 batch 近似视图和被忽略的 SHELX data cards，不把它称作完整 SHELXL 作业重放。只读顾问可复制真正绑定的历史节点与观测，仍不复制凭据/整段历史，也不打开父项目的锁。
- 新只读 `/api/wb/refine/comparison?project&node&baseline` 返回双方实际 metric source、条件差异及每项 `comparable/different/unknown`。记录 SHELXL 实际使用的 WGHT，而非 RES 尾部建议下轮 WGHT；`mask` 是测量实际使用条件，`stored_mask` 是仍可供后续操作使用的快照，两者不混同。相同观测、选择和已知定义下，坐标/H/占有率/拟合尺度变化属于被比较模型变量，不使 R1 自动不可比；不同权重主要约束 wR2/GooF，不同实际 cutoff/selection 则约束 R1。数值下降不是结构质量胜出，GooF 也不是越低越好。
- Frame 只描述可确认的坐标参照；相同晶胞/群不证明同基底/原点，同 frame 更不证明同 label 就是同一原子。UI 比较单元独立消费这些字段，本单元不实现原子映射或修改渲染器。

已实际执行的公开科学对照（不是模型调用）：蔗糖原始 embedded HKL 零周期 R1/wR2/GooF 为 **0.0411/0.1100/0.972**；同模型显式换发表 SF 转换的另一观测版本后为 **0.6148/0.0847/0.186**，不是科学改善。Checkout A 恢复精确 HKL 字节及原三项指标。CuBTC COD 2206821 四周期为 **0.0244/0.0838/0.731**，重新打开绑定节点后零周期 R1 一致；不把它误称为 HKUST-1。独立 HKLF5 用例逐字节保留正/负 batch、换行和 trailer，并恢复真实复数 Miller mask 快照、SHEL/OMIT 与权重。所有这些项目/pytest basetemp 在独立外部目录，不改原始源项目或 8010。

验收：最终发布组合 **436 passed / 2 skipped**（缺 CAP 原始产品，以及未显式启用的真实 PLATON 发布-CIF 格）；所有新增真实 HKL/指标、spawn、历史数据绑定测试均执行。最终缺失/损坏 mask 的 map guard 专项 **5 passed**，其中 3 项与组合重叠，不重复累计。TypeScript 检查与 diff whitespace 检查通过。原来依赖缺失 SJTU-9 HKL 的 map/void/data-summary 形状测试改为外部、明确绑定的合成 cctbx 输入；它们不是新增真实 MOF 科学通过证明。真实公开对照与这些合成契约测试分别报告。

回滚必须把版本存储、读写入口和恢复逻辑作为同一后端单元处理：先由项目所有者停止合作写任务，用当前实现完成 pending publication；保留版本和 journal，不能删 marker 强行恢复。旧软件不了解历史数据绑定，不允许它在受影响历史上重新计算；需要旧版本时先显式导出一个已绑定状态到独立项目，或保持项目只读。审批自动绑定、调用幂等、旧外部文件的追溯恢复仍是后续工作。

## 12. 本轮最终收尾与 Claude Code 交接（2026-09-08）

**本轮实施、集成与生产验收完成；不再启动下一阶段。** 前端功能已集成于 `e07a33b`，反射版本后端已集成于 `46d0be3`。最后补存真实比较 oracle 测试及证据，不增加模型调用或改变科学模型。

### 最终验收

| 验证组（相互可能重叠，不相加） | 结果 |
|---|---|
| 父级最终后端回归 | 149 passed，194.06 秒 |
| 父级完整 UI Vitest | 50 文件、529 passed |
| 集成生产 build | 通过；原有 3Dmol eval 警告保留 |
| 更新后的生产 8010 浏览器 | **12 passed / 0 skipped**，39.9 秒 |
| 新版 API 与持久化 node.json 来源对账 | 六组预设科学判定全部一致 |

生产浏览器的 12 项为：六组真实科学条件 oracle、一个强制 bound 来源/只读/引用/焦点恢复测试、五种宽度/配色布局。请求门禁只放行读取及 `POST /api/projects/open`，没有模型、设置或 checkout 写入；各用例核对活动节点与节点记录未变。这里只运行生产适用用例：此前静态全比较组为 8 passed / 3 skipped，三个 Vite 公共 Viewer 探针另有前期实测，不算此次生产通过。

| 真实比较情景 | R1 | wR2 / GooF |
|---|---|---|
| 同数据加氢后重新测量 | comparable | comparable |
| 仅加氢、沿用旧指标 | unknown | unknown |
| 实际 WGHT 改变 | comparable | different |
| 截断改变，实际反射 1755 → 908 | different | different |
| 蔗糖换成另一观测版本 | different | different |
| 原 Sol 旧节点来源未绑定 | unknown | unknown |

科学预期事先独立列出，不从 DTO 生成预期。最终再逐节点核对 comparison/node-list 的模型修订和磁盘 `node.json` 的 data revision。真实回放维持 **R1 0.0411 → 0.6148 → 0.0411**、精确观测字节恢复；跨样本实验上下文恢复为 **298 → 293 → 298 K**，旧节点未追改。

- [机器可读最终来源与验收摘要](evidence/2026-09-08/versioned-closeout.json)
- [独立比较预期与本机项目位置](evidence/2026-09-08/comparison-oracle-cases.json)
- [真实权重变化与逐指标条件](evidence/2026-09-08/comparison-weight-conditions.png)
- [390px 已绑定比较界面](evidence/2026-09-08/comparison-bound-390.png)
- 完整本机日志：`workdir\round3-final-backend-tests.log`、`round3-final-ui-tests.log`、`round3-production-build.log`、`round3-production-browser.log`；截图在 `workdir\ui-evidence\round3-production-closeout`。

在本 worktree 复跑生产比较（需保留清单中的外部验收项目）：

```powershell
$env:CP_BASE_URL = 'http://127.0.0.1:8010'
$env:CP_COMPARISON_CASES = Join-Path (Get-Location).Path 'docs\evidence\2026-09-08\comparison-oracle-cases.json'
$env:CP_E2E_PROJECT = 'H:\CrystalPilot-campaigns\upgrade-20260908-data-acceptance\versioned-small-pair'
$env:CP_COMPARE_NODE = 'n0003'
$env:CP_COMPARE_BASELINE = 'n0001'
$env:CP_COMPARE_REQUIRE_BOUND = '1'
$env:CP_EVIDENCE_ROUND = 'round3-production-recheck'
Set-Location '.\ui'
npm run e2e -- comparison-oracle.pw.ts structure-comparison.pw.ts --grep 'real comparison oracle|real pair stays|real comparison layout'
```

### 服务与安全停点

- 8010 已使用本 worktree 的集成后端及新静态包，健康响应 `ok=true`、`ui_build.stale=false`；前端构建时间为 `2026-09-08T07:40:40.991Z`。重启前后 provider API 记录逐项一致，没有重写 gateway/OpenRouter 配置或密钥；健康接口的旧求解器 `llm_configured` 字段不代表工作台 provider 配置丢失。
- 保留用户要求的**独立后台 8010**，本次监听 PID **45600**；权威运行信息在 `workdir\services\8010\service.json`，日志路径由该文件给出。仍使用隔离 `workdir\audit-codex-home`、2 核预算和 SelectorEventLoop，未添加开机启动。
- 已确认注册的 10 个项目均无活动回合、无 pending `publishing.json`；未删除锁、journal 或数据版本。旧 8010 的已核实进程树已停止。临时 QA/Vite 端口已无监听，无活动后台任务代理；两实施子会话此前已冻结交付，不再安排工作。
- 重启前 UI 与服务元数据保存在 `workdir\services\8010\ui-before-versioned-closeout`、`service-before-versioned-closeout.json`。旧 UI 备份不是允许旧后端重算版本化历史的授权；后端回退必须遵从 §11。
- **不要直接归档/删除这个 worktree**：8010 依赖其源码、虚拟环境和隔离配置。停止服务前按 `service.json` 核对 PID、创建时间和所属进程树，只停止确认拥有的进程。

### Claude Code 从哪里继续

代码在分支 `topospace-crystalpilot-system-review`，尚未合入 `main`、未 push/创建 PR。请让 Claude Code 使用当前工作树：

```text
D:\worktrees\CrystalPilot\topospace-vigilant-couscous
```

先读 `ARCHITECTURE.md` 和本文 §9–12。不要把 `H:\CrystalPilot` 主检出当作已更新版本；科学项目继续放在仓库外。下一阶段候选已列于 §9，本轮没有承诺或偷偷启动这些工作。

## 13. 已合入 main（Claude Code，2026-09-08 晚）

上一节的状态已经过时：`main` 已从 `0f5848f` 快进到 `c4f0523`，之后追加 `67c4798`（受控导入后首次 checkout 重复解析反射文件的回归）与 `bdfbbec`（旧节点的孔道块按 §11 改为几何可用，13 个随分支带进来的失败测试改为显式绑定旧夹具）。H 盘环境核验、隔离冒烟与正式 8010 的迁移记录在 `docs\MERGE-2026-09-08-main-acceptance.md`。注意本轮实验跑在 pip 0.147 内核上，H 盘正式服务用的是 npm 0.153.4。
