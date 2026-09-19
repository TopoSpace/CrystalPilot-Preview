# 第三轮 R6 复盘：人机交互：提问卡、引用芯片、插话回执、知识模式（2026-09-06）

> 对应计划 `docs/PLAN-2026-09-05-round3.md` §3 R6。代码、测试与 UI 证据已收口；**计划里的真实交互实验一格（先无先验 → 提问卡 → 用户补一条真实先验 → 有界二轮）在本轮被模型 API 挡住**：三次启动的预热回合都以 `stream disconnected before completion: stream closed before response.completed` 失败（见 §5），按主人 09-06 的指示暂停实机测试、继续系统工作；API 恢复后复跑并把结果追加到本文。

## 1. 目标对照

| 计划项 | 结果 | 提交 |
|---|---|---|
| 提问卡：Agent 缺关键事实时输出结构化 `[ask …]`，前端渲染为卡片，用户点选即作为先验（标 `user_prior`），主 Agent 用数据验证；AGENTS 给格式与触发条件 | ✅ 格式定为 ```` ```ask ```` 围栏内一段 JSON（settled / dispute / question / options / fallback）；模板 v40 新增"问人（提问卡）"节；对话里渲染为静态卡，最新未答的一张停靠在输入框上方，按钮一键回复 `[prior] 问题：…\n回答：…`（运行中走插话，空闲走发送），"自己回答"把同样的抬头放进输入框 | `b42b9ca` |
| 引用升级：输入框内芯片（保留纯文本回退）；锚可点击回到该节点/原子/对称像并标"历史值"，不自动检出 | ✅ 输入框上方"引用"栏列出草稿里的每个 `[anchor …]`（可移除，文本仍是唯一真值）；对话里的锚芯片变成按钮：查看该节点（历史视图，右栏"正在查看历史节点 nXXXX"横幅 + 返回最新）并选中第一个原子（`O1(-x,y,-z)` 先找该对称像，没画时退回 ASU 原子）；reducer 记住"等哪个节点的场景"，不会在旧节点的场景里误选 | `b42b9ca` |
| 插话确认：accepted / persisted / submitted-to-model 三态回执；失败可重试 | ✅ 服务端在 `user_steer` 之后立刻记 `steer_receipt {steer_eid, status: submitted \| failed, error}`（transcript + 直播通道，刷新后同样三态）；气泡显示 发送中 → 已记录 → 已送达模型 / 未送达模型 + 重试；`POST /api/threads/steer` 返回 `receipt` | `b42b9ca` |
| 知识模式与结构类别进设置面板 | ✅ 权限芯片菜单"项目设置"里新增 知识模式（完整 / 纯工具，运行中切换返回 409 并提示）与 结构类别（服务端类别表，未声明可选） | `b42b9ca` |
| 真实数据：交互实验一格 | ⏸ 三次启动（04:10 / 04:14 / 04:18）预热回合均在 16 s 处被上游断流；已按指示暂停，脚本、简报与先验文件就位（§5） | — |

## 2. 做法要点

### 2.1 提问卡协议（模板 v40）
- 触发条件写成证据语言："缺一件**会改变下一步**的事实（投料/客体/溶剂/是否接受非发表级候选）而数据定不了时，不猜、不双线并行"；一回合最多一张卡；能自己查的不问；发卡后结束回合等用户。
- 回答以 `[prior]` 开头回来：模板明说它是用户先验不是数据证据，记进 `set_investigation` 并用数据验证；"不知道"走 fallback。
- 模板预算：delegate 变体 8994 → 8998 / 9000。新增约 330 字，靠等义压缩腾出（铁律里四条"某某格"的出处括号、技能库/专家子代理/自定义计算段、checkCIF 尾句、开头一句），没有删任何"牙"（`test_template_stays_lean_and_keeps_teeth` 的 14 个针全在）。
- 前端解析宽容：围栏里不是 JSON 时退化为"只有问题"的卡，不会消失；选项最多四个；"仍未回答"的判定只有一条，最后一条 Agent 消息带卡、已流完、之后没有用户消息也没有更晚的 Agent 消息（Agent 自己接着说了就视为它走了 fallback）。

### 2.2 插话回执
- 三个事实各有各的来源：接受 = 乐观气泡（HTTP 尚未返回）；已记录 = `user_message/user_steer` 带 eid 到达（transcript 已写）；已送达 = 应用服务器接受了 `turn/steer`（`steer_receipt.submitted`）；未送达 = `turn/steer` 抛错（`failed` + 错误文本），此时用户的话仍在 transcript 里，气泡给"重试"再发一次。
- 回执按 `steer_eid` 对应气泡，没有 eid 的直播事件退回"最近一条还没回执的插话"；回放旧 transcript 得到同样状态（`threadReducer.receipt.test.ts`）。
- 边界：回执确认的是应用服务器收下了插话，不是模型"读到了"；这一层 Codex 没有更细的信号。

### 2.3 引用芯片与锚跳转
- 草稿芯片：`anchorTokens(text)` / `removeAnchorToken(text, token)` 纯函数（`anchorTokens.test.ts`）；移除时连带一侧空格，句子合拢。
- 锚跳转：`CrystalProvider.selectLabel(node, label)` = `view_node` + `select_label`；reducer 新增 `sceneNode`（当前场景属于哪个节点）与 `pendingSelect`，只有"看的节点 = 场景的节点 = 锚的节点"才立即选中，否则等该节点的 `scene_ok`；用户中途换看别的节点则丢弃待选（`crystalReducer.select.test.ts`）。
- 仍未做：锚只选第一个原子；"历史值（n0116）"标记靠现有历史横幅与芯片 title，没有在对话侧额外渲染当时的数值。

### 2.4 设置
- 服务端本来就持久化 `knowledge_mode` / `structure_class`，只是 UI 没有入口；现在 `WorkbenchProvider.changeKnowledgeMode`（409 → "运行中不能切换知识模式"）与已有的 `changeStructureClass` 一起进权限菜单。

## 3. 证据

- vitest 342（39 文件；新增 `askCard.test.ts` 12、`anchorTokens.test.ts` 5、`threadReducer.receipt.test.ts` 5、`crystalReducer.select.test.ts` 7）；tsc 干净。
- pytest：`tests/test_steer_receipt.py`（3：submitted / failed 保留原话与错误 / 空闲无回执）；模板守卫 `test_agents_md` + `test_upgrade_instructions` + `test_pa2_tool_fixes` + `test_absence_wording` + `test_skills` 76 passed；工作台子集（workbench / routes / service / channel / transcript / settings / roles）132 passed；全量见 `docs/UI-EVIDENCE-2026-09.md` 第三轮 R6 节。
- Playwright 证据轮 **r3-r6**（`workdir/ui-evidence/r3-r6/`）：`e2e/r6-interaction.pw.ts` 在 Zr6 笼真实项目上 2 passed（浅 / 深），**UI 证据而非科学证据**：真实 transcript 末尾由路由拦截追加一段明确合成的尾巴（一张卡、两条带回执的插话），send/steer 端点被拦截，没有消息到达模型。断言：卡在对话与停靠区都出现；"已送达模型"与"未送达模型 · 重试"各一条；点"有"后请求体正文恰为 `[prior] 问题：合成时是否加入了对溴苯乙酸？\n回答：有` 且停靠卡消失；点锚芯片后身份栏显示锚的节点；草稿里的锚变芯片、移除后文本为"看看 附近的密度"；设置菜单里知识模式/结构类别两行可见。截图 `r6-{light,dark}-{card-receipts,anchor-jump,quote-chip,settings}.png`。

## 4. 没做 / 边界

- 提问卡没有服务端强制：Agent 不按格式写就没有卡（只有普通文字）；`[prior]` 也只是约定的抬头，不是新的事件类型。
- 回执到"应用服务器接受"为止。
- 锚只选第一个原子；没有把"当时的数值"回填到对话侧。
- 知识模式切换在回合运行中被拒绝（服务端规则，改模板需重建服务）。
- 交互实验一格未跑（API）。

## 5. 实机记录（2026-09-06）

| 时间 | 项目 | 结果 |
|---|---|---|
| 04:10 | `H:\CrystalPilot-campaigns\r3\r6-mof-ask` | 预热回合失败：`stream disconnected before completion: stream closed before response.completed`（16.6 s） |
| 04:14 | `…\r6-mof-ask-b` | 同上 |
| 04:18 | `…\r6-mof-ask-c` | 同上 |

- 三个项目都已建好（输入就位、AGENTS v40 已写入），只是没有开始；API 恢复后用同一简报与先验复跑：
  `scripts/run_live.py --source H:/CrystalPilotData/staging/r25a --name r6-mof-ask-d --brief workdir/live-demos/briefs/r6-mof-ask.md --context workdir/live-demos/contexts/r6-mof-ask.json --title "R6 提问卡实验 · Zr-MOF（无配体先验）" --structure-class framework --strip-placeholders --hours 1.5`
- 实验设计：`contexts/r6-mof-ask.json` 只保留"金属来源只有 Zr"，去掉 TBAPy 类配体与对溴苯乙酸处理两条先验；简报提示"缺少能改变下一步判断的事实时按提问卡提问"。预期 Agent 在建模前问配体/客体；回答用主人 09-05 简报里的原话（`contexts/r4-mof.json` 的 chemistry.note）作为 `[prior]`，观察它是否记入 `set_investigation` 并用数据验证，以及二轮是否有界。
- 判读维度（复跑后填）：是否出现提问卡、问的是不是"会改变下一步"的事实、回答后调用数、墙钟、是否把先验当证据。

## 7. GLM 复跑（2026-09-06 08:20 起，OpenRouter 临时渠道）

网关仍断流，主人 08:00 给了 OpenRouter 的 key（GLM-5.3 / GLM-5.3 Flash，推理档 high；预期不如 GPT，结果差先分清是基模还是系统）。接入方式与两处通用修复见能力表 §4 内核行与 §8。

| 格 | 模型 | 结果 |
|---|---|---|
| r6-mof-ask-glm（08:20） | z-ai/glm-5.3 @ high，视觉未关 | 22 min 后死于 `view_structure`：GLM-5.3 是纯文本模型，OpenRouter 对带图请求 404，图片留在历史里线程作废。此前 20 分钟：读简报、数据审计（R_int 0.631、\|E²−1\| 1.30）、五候选群、L 检验判部分孪晶、`set_investigation` 因把 `tiers` 双重编码成字符串失败四次后放弃、SHELXT 21 min 得弱解（CFOM 0.5，R1 0.45） |
| r6-mof-ask-glm2（08:50） | z-ai/glm-5.3 @ high，`vision=false` | 数据审计 → 分辨率截到 0.997 Å → SHELXT 22 min 弱解 → 重解 → 对称审计 → **09:26 发提问卡**（问投料配体，四行齐全，停靠卡 + 三个选项；截图 `workdir/ui-evidence/r3-r6-live/glm2-ask-card-before-answer.png`）→ 09:27 我用主人 09-05 简报原话作 `[prior]` 答复 → Agent 记入 `set_investigation`（这次参数解码成功）、`check_ligand` 模板匹配 RMSD 0.073 Å、`fit_fragment` 因差值密度 0.25–0.57 e/Å³ 被诚实门拒绝、`element_scan` 排除 Zr 占有率、`search_fragment_pose` 跑到 09:32 被中断（主机 09:35 由 AweSun 发起重启，服务与跟随器全没）。10:03 服务重启、线程 resume 继续：`validate_structure`、删重复位、`analyze_packing`（约 78 % 孔体积、~780 e/胞）、Zr 无序分支（FVAR s.u. 0.65 → inconclusive，不采纳），10:20 Agent 读到"图片已存盘"后用 Codex 自带 `view_image` 打开 PNG → 再次 404、线程作废。修好 `view_image` 关闭后 10:24 在同一项目开新线程从 n0027 续接（先验随简报带上），见下一行 |
| r6-mof-ask-glm2 续接线程（10:24） | 同上，`view_image` 已关 | **一个工具都没调成**：首回合 4 次 get_project_brief 全被 Codex 回 "unsupported call"，Agent 放弃；10:28 我发"继续"，它只回一句"MCP 已恢复。我先按顺序核对…"就结束回合（宣布而不调用）。从 Codex 自己的日志库（`codex-home/logs_2.sqlite`，含每次 POST 正文）查明：codex 0.147 把 74 个 MCP 工具打包成**一个** Responses API 命名空间工具 `mcp__crystalpilot`，模型每次调用都必须回带 namespace 字段；GLM-5.3 这一线程首次调用漏掉了它（探针线程与首格 40 余次调用都带了，属间歇性）。0.147 已无 chat 线路可退。处置：第三方提供方的线程在 developer 指令里写明命名空间与"unsupported call = 缺命名空间，带上重发；不要只宣布不调用"（`core.py new_task`），监控脚本对"回合结束且无任何工具调用"自动催一次（最多 3 次） |
| r6-mof-ask-glm2 续接线程 3（10:46） | 同上 + 命名空间说明 | **10:46–12:01 一气跑完：83 次工具调用、0 次催促、无新提问卡**（先验已随简报带上）。路径：核对 n0027 → 只读审计（validate / 元素标签 / compare_nodes：Zr 无序分支 GooF 2.51 不采纳）→ analyze_packing（单一 3D 网 csq、无互穿；C15X 归为 12 个孔内自由位）→ ghost_test（C15X 判 real 但 possibly_non_atomic，Ueq 0.43）→ 数据侧核查（反射统计 / 重复观测 / check_symmetry：无超胞指数、无额外算符）→ 删 C15X（acknowledge_real）→ 加骑乘 H → 各向异性精修 → 掩膜→ 孔轴 Br 探针（自由占有率精修到 0.0001，omit 图 0.82 e：只否决该位点）→ 端氧 OH 与双位无序两条对照分支都被精修否决并撤销（revoke，SADI 5.5σ）→ SHELXL 权重收敛→ checkCIF 三轮（PLAT201 追到撤销分裂时被重置为各向同性的 O3/O6）→ **1000 轮 BYPASS 未收敛就不肯交付**：5000 轮在第 1743 轮整体判负被丢弃，改 0.33 粗网格 35 轮收敛 743.4 e/胞，并如实写明同一模型电子数随网格从 441 摆到 743→ 同步辐射波长记入 experiment 消掉一条 A → 中文 SUMMARY / VALIDATION → 12:00 诊断性封存 n0064。终态 R1(I>2σ) 0.0812 / wR2 0.2445 / GooF 0.900 / Δρ +0.52/−0.81 e Å⁻³；checkCIF A8 B1 C24（A 全是 Rint 0.57、0.997 Å 分辨率与缺失实验元数据）。截图 `workdir/ui-evidence/r3-r6-live/glm2-thread3-delivered*.png`。**观感**：GLM-5.3 全程用证据语言、两次否决自己的假设、拒绝把未收敛掩膜交付；比 GPT 的 R4 复跑（117 节点、3 h+）短得多，但没有再做整客体姿态搜索（search_fragment_pose 只在首线程试过一次），客体问题以"该位点否决"收尾。**系统侧新线索**：掩膜电子数对网格参数敏感（0.25 网格 1000 轮未收敛 441 e vs 0.33 网格 35 轮 743 e），BYPASS 的整体判负丢弃也再次出现，下一轮候选 |
