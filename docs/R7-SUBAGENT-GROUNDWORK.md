# R7 子代理实验地基（2026-09-05）

范围：round-2 R7（`docs/PLAN-2026-09-04-round2.md` 1.2 节 + "R7" 节）要求的地基工作，查清 Codex 原生 `spawn_agent` 多代理机制在当前版本下的确切行为、为四个只读审计角色打样 TOML、写一个不触网关/不起会话的 pytest。

方法论声明：本文档全部结论来自（a）对本仓库/本 worktree 源码的只读阅读，（b）对已打包 Codex 二进制的只读、非交互调用（`--version` `--help` `features list`），（c）对官方文档页与 GitHub issue 的网页抓取。**没有启动任何交互式会话、没有跑 campaign、没有起 workbench server、没有调用任何模型/网关、没有读写 `testAPI.txt`、没有改动 `codex-home/config.toml` 或任何 `crystalpilot/` 下的 `.py` 文件。** 凡未能独立验证的结论，下面都明确标注"未验证"，不做猜测性断言。

---

## a. Codex CLI 版本

```
$ H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -c \
    "from codex_cli_bin import bundled_codex_path; print(bundled_codex_path())"
H:\CrystalPilot\.venv\Lib\site-packages\codex_cli_bin\bin\codex.exe

$ <该二进制> --version
codex-cli 0.147.0
```

`openai_codex`、`openai_codex_cli_bin` 两个 Python 包的 dist-info 元数据版本号同样是 `0.147.0`，三处一致。

`--help` 顶层子命令：`exec / review / login / logout / mcp / mcp-server / app-server / resume / fork / apply / cloud / sandbox / debug / features / completion / doctor` 等；关键全局参数：`-s/--sandbox {read-only,workspace-write,danger-full-access}`、`-a/--ask-for-approval {untrusted,on-request,never}`、`-c/--config key=value`（任意 config.toml 键覆盖）、`--strict-config`（拒绝未知配置键，但只对*会话型*子命令生效，`--strict-config completion bash` 和 `--strict-config features list` 都报错"not supported for codex completion/features"，本次没有为了验证而去起一个会话型子命令，因此现有 `config.toml [agents]` 里几个字段是否仍被 0.147.0 识别，留在下面"未验证"部分）。

用 `codex.exe features list`（离线、只读、不连网关）额外确认了一个和现有代码注释不一致的地方：

| 字段 | 状态 | 值 |
|---|---|---|
| `multi_agent` | stable | **true**（开） |
| `multi_agent_v2` | stable | **false**（关） |
| `multi_agent_mode` | removed | false |

来源：`codex.exe features list` 本次实测输出。`crystalpilot/workbench/core.py` 里有注释说"Codex has multi_agent v2 ON in every session"，`codex-home/config.toml` L23-24 的注释也写"capability is ON by default in codex 0.147 (multi_agent v2, 4 slots)"——但本机这份 0.147.0 二进制上，真正打开的是不带 "v2" 后缀的 `multi_agent`，`multi_agent_v2` 明确是 false。这不影响功能本身（`spawn_agent` 走的就是 `multi_agent` 这条稳定通道），但两处注释里"v2"的表述与本次实测不符，建议以后改注释时一并订正。

---

## b. 自定义 agent 角色怎么定义

**位置**：官方文档（`developers.openai.com/codex/subagents`，301/308 跳转到 `learn.chatgpt.com/docs/agent-configuration/subagents`）说独立 TOML 角色文件放在两个位置之一：
- 个人级（跨项目复用）：`~/.codex/agents/*.toml`
- 项目级（仅该项目、且项目须是 trusted）：`<project>/.codex/agents/*.toml`

CrystalPilot 把 `CODEX_HOME` 整个搬到了 `H:\CrystalPilot\codex-home`（隔离用户本机真正的 `~/.codex`，`crystalpilot/workbench/core.py` 里能看到这个环境变量设置），所以"个人级"位置在本项目里就是 **`codex-home/agents/*.toml`**：与任务假设一致。已确认这个目录本次之前不存在（`ls codex-home/agents` 报 "No such file or directory"），本次已创建。

没有选"项目级"（`<project>/.codex/agents/`）的原因：GitHub `openai/codex#26408`（2026-06 开的 issue，本次抓取时仍 open）的复现步骤显示，全局/个人级角色可以用 `spawn_agent(agent_type="oracle-devtools")` 成功拉起，但**项目级**同名机制当时复现为"agent type is currently not available"。选个人级位置正好绕开这个已知未修的坑。另有一条更早关闭的 issue `openai/codex#15250` 提到过"tool-backed"（也就是 app-server/JSON-RPC 驱动，而不是交互式 TUI）会话里按名字拉自定义 agent 失败的情况；这条 issue 已关闭但看不到明确的修复说明，其结论是否已被 0.147.0 修复未验证，这正是下面"决策"里的第二条。

**TOML 字段**（官方文档枚举）：必填 `name`、`description`、`developer_instructions`；可选 `model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers`、`skills.config`。文档给的 `mcp_servers` 示例是覆盖一个 `url` 型（远程 HTTP）MCP 服务器，没有给 stdio 命令+环境变量的示例。

**继承规则**（同一页文档，WebFetch 只能给出转述而非逐字引用，下面是转述，务必核对原文再作为强约束依据）：
- 如果角色文件设置了 `model` 或 `model_reasoning_effort`，文件里的值优先；否则解析顺序是"显式 spawn 参数 → `[agents]` 里对应的默认值 → 父 agent 当前值"。
- `sandbox_mode`、`mcp_servers`、`skills.config` 等字段：角色文件不设置就从父 agent 继承。
- **但是**：文档明确说 Codex 在派生子线程时会"重新套用父 turn 当前生效的运行时覆盖（比如 `/permissions` 改过的权限、或 `--yolo`），即使被选中的自定义角色文件设置了不同的默认值"。也就是说角色文件里写的 `sandbox_mode = "read-only"` **不一定**是最终生效值，如果父 turn 当时处于一个更宽松的实时覆盖状态,这条覆盖可能盖回子线程上。这一条对下面"决策 1"很关键。

**MCP 环境变量**：`developers.openai.com/codex/extend/mcp`（跳转 `learn.chatgpt.com/docs/extend/mcp`）确认 stdio 型 `[mcp_servers.<name>]` 支持 `command`、`args`、`cwd`、`env`（字面环境变量表，文档原文给的例子是 `[mcp_servers.context7.env]` / `MY_ENV_VAR = "MY_ENV_VALUE"`）、`env_vars`（转发白名单）、`startup_timeout_sec`（默认 10）、`tool_timeout_sec`（默认 60）、`enabled`、`required`、`enabled_tools`/`disabled_tools`、`default_tools_approval_mode`、以及每个工具自己的 `tools.<tool>.approval_mode`/`output_token_limit`。

这与 `crystalpilot/workbench/core.py` L56-90 的 `_mcp_overrides()` 基本对得上（它生成 `mcp_servers.crystalpilot.{command,args,cwd,env,startup_timeout_sec,tool_timeout_sec,approval_mode}` 这些 `-c` 覆盖），但有一处命名对不上：`_mcp_overrides` 用的键是裸的 `approval_mode`（L89），今天抓取的文档页给的名字是 `default_tools_approval_mode`（服务器级）或 `tools.<tool>.approval_mode`（单工具级），没有 `approval_mode`（裸）这个名字。这套系统显然在生产里一直正常工作，所以 `approval_mode` 大概率是仍被 0.147.0 接受的旧别名，但文档层面对不上，未去动 `.py` 文件核实，列为"未验证"。

**`spawn_agent` 怎么选角色**：参数名是 `agent_type`，取值就是角色文件的 `name` 字段（来源：`openai/codex#26408` 的复现步骤 `spawn_agent(agent_type="oracle-devtools")`；官方文档也说"Codex 用 `name` 字段识别自定义角色"）。这个参数/工具本身在 Python SDK（`openai_codex/generated/v2_all.py`）里找不到对应的 wire-protocol 消息类型，推断是 Rust Codex core 直接把这个工具描述喂给模型的原生工具，不经过我们现有的客户端类型定义，所以 CrystalPilot 这边没法在 SDK 层面校验 `agent_type` 拼写是否有效,只能靠角色文件名与 `name` 字段保持一致（`tests/test_codex_agent_roles.py::test_role_name_matches_filename` 已经断言这一点）。

**沙箱是否覆盖 MCP 工具调用**：官方沙箱文档（`developers.openai.com/codex/concepts/sandboxing` → `learn.chatgpt.com/docs/sandboxing`）只讲了 shell 子进程的文件系统/网络边界，通篇没提 MCP 工具调用是否在这个边界内。`crystalpilot/workbench/core.py` L63-65 自己的注释是"the MCP process is NOT under the codex sandbox, so the read-only permission mode needs this server-side gate"——外部文档既不证实也不否认这条,只能说不矛盾。这也是为什么 CrystalPilot 现有的 `consult_specialist` 机制（`crystalpilot/refine/tools_specialist.py`）完全不依赖 `sandbox_mode`,而是直接给 MCP 服务器进程注入 `CRYSTALPILOT_MCP_READONLY=1`（该文件开头文档字符串原话："The specialist thread runs with CRYSTALPILOT_MCP_READONLY=1 - its MCP server refuses every mutating tool in-process"）。这一条是"决策 1"的核心证据,详见下文。

---

## c. 推理效力梯度

SDK 枚举（`H:\CrystalPilot\.venv\Lib\site-packages\openai_codex\generated\v2_all.py` L3204-3210）：

```python
class ReasoningEffort(str, Enum):
    none = "none"
    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"
```

没有 `max`/`ultra` 这一档。它还带一个 `_missing_`（L3212 起）,对识别不了的字符串直接放行、不报错，也就是说客户端 SDK 层面不会拒绝任何非法档位字符串,真正的校验在网关那一侧。

`crystalpilot/workbench/service.py` L86：`EFFORT_CHOICES = ("low", "medium", "high", "xhigh")`,紧邻的注释（L82-85）说这是"SDK 枚举与 gpt-5.6-sol 网关实际接受值的交集（实测过：'minimal' 被网关拒绝；'max' 网关那边存在但 SDK 枚举里还没有）"。这条注释是**之前**的既有记录,本次任务明确要求不得调用模型/网关,所以没有重新探测网关侧是否真的接受 `"max"`，只确认了"SDK 枚举没有 max/ultra"这一半,`"max"` 是否网关侧真实存在维持既有注释、不算本次验证。

档位梯度上限选 `xhigh` 是稳妥的（SDK 与 UI 两边都封顶在这里）;如果以后要试更高档,得先在允许调用网关的场合单独探测,而不是写进这次的地基文档里当作已验证事实。

---

## d. 档位门控段落草稿（中文，406 字，预算 600 字以内）

> 当前推理档位为本项目最高档（xhigh）时，你可以并行委派只读审计给四个专长子代理：space_group（空间群/对称性）、chemistry（化学建模合理性）、density（差值密度解读）、validation（checkCIF 复核）。用 spawn_agent(agent_type="...") 委派，它们的 MCP 连接按只读方式启动，写类工具会被拒绝，你始终是唯一的写者与最终裁决者。
>
> 只在真正有分歧的节点委派：空间群存疑、密度峰身份不明、化学证据与合成先验矛盾、交付前复核警报，不要在常规步骤上用它们，一次委派要占掉一整轮对话和数分钟墙钟。
>
> 子代理的判词只是参考意见，不是结论：把它的 evidence 和你自己已核实的工具结果逐条对照；它证据更扎实就采纳并说明理由；它引用的数字与你实测不符，以你自己的验证为准并记录分歧；不要因为它语气更肯定就采纳，它看到的节点历史和证据都可能比你少。

**重要限定**：这段话里"MCP 连接按只读方式启动，写类工具会被拒绝"这句是在假设"决策 1"已经被 R7 实跑验证为真的前提下写的，目前这只是设计意图,不是已确认行为（见下方决策 1）。如果 R7 实跑发现这条不成立,这段落必须先改措辞或加限定语再注入 AGENTS 模板,不能原样上线。字数用 `H:/CrystalPilot/.venv/Scripts/python.exe` 对纯文本（不含 Markdown 引用符号 `> `、不含段落间空行）计数为 406 字符,在 600 字预算内留了余量。

---

## e. config.toml 注册片段提案

**结论：大概率不需要新增片段。** 根据 b 节文档,`codex-home/agents/*.toml` 下的独立文件靠文件存在 + `name` 字段就能被 `spawn_agent(agent_type=...)` 发现,不需要在 `config.toml` 里再声明一遍。（另有一处置信度较低的社区资料提到过 `config.toml` 里也能写 `[agents.<name>]` 子表来登记角色，这是与"独立文件"平行的另一套机制,官方文档主推的是独立文件这条路,四个角色文件已经用的也是这条路,不建议再叠加 `[agents.<name>]`,以免两套来源打架。）

唯一值得主线权衡、并列在这里当"提案"的,是现有 `[agents]` 里的并发上限：

```toml
# 现状（codex-home/config.toml L27-31，未改动）：
[agents]
max_concurrent_threads_per_session = 2
max_depth = 1
job_max_runtime_seconds = 1800
default_subagent_reasoning_effort = "medium"
```

R7 的四个角色如果哪天真的"并行委派给四个专长子代理"（d 节草稿的字面意思）,单个 session 最多只能同时开 2 个子线程,第 3、4 个会怎样（排队？拒绝？）本次没有验证。**提案**：先不改这个数字，`docs/PLAN-2026-09-04-round2.md` 自己的风险提示写着"子代理成本高（r23 1.7M tokens）→ 默认关；实验只一格",维持 2 与"先小规模试、别一次烧四份"的谨慎态度更一致;如果 R7 试验之后证明单次成本可接受、确实需要四路并行,再把这个数字提到 4,并同时想清楚 d 节段落要不要显式加一句"最多同时开两个"。

---

## 交付物清单

| 文件 | 说明 |
|---|---|
| `docs/R7-SUBAGENT-GROUNDWORK.md` | 本文档 |
| `codex-home/agents/space_group.toml` | 只读角色：空间群/对称性审计，`model_reasoning_effort = "medium"` |
| `codex-home/agents/chemistry.toml` | 只读角色：化学建模合理性审计，`model_reasoning_effort = "high"` |
| `codex-home/agents/density.toml` | 只读角色：差值密度解读，`model_reasoning_effort = "high"` |
| `codex-home/agents/validation.toml` | 只读角色：checkCIF/结构验证复核，`model_reasoning_effort = "medium"` |
| `tests/test_codex_agent_roles.py` | 只解析 TOML + 查必填字段 + 查 instructions 不提任何 `MUTATING_TOOLS` 工具名的 pytest |

四个角色文件都：
- `sandbox_mode = "read-only"`；不写 `model` 字段（留空以继承父 agent，见 b 节继承规则）。
- `developer_instructions` 取自 `crystalpilot/refine/tools_specialist.py` L29-60 对应 `SPECIALTIES["space_group"|"chemistry"|"density"|"validation"]` 的 `brief`，改写成子代理能独立理解的完整提示（角色文件没有像 `_specialist_prompt()`（同文件 L183-199）那样的外层包装，所以每个角色文件自己带齐了身份说明、可用只读工具清单、诚实守则、以及收尾的结构化 verdict 格式要求）。
- 收尾 verdict 的字段形状对齐 `VERDICT_SCHEMA`（同文件 L62-78）：`assessment / recommendation / confidence / evidence / risks`，但这是**写在 prompt 文字里的要求**，不是像 `_run_specialist_turn()`（同文件 L203-248）那样通过 `TurnStartParams.output_schema` 强制的 JSON Schema 约束。`spawn_agent` 这个原生工具本身，在 SDK（`v2_all.py`）里找不到任何 schema 约束参数，所以子代理是否真的吐出合法 JSON，只能靠 prompt 措辞约束，约束力比 `consult_specialist` 现有机制弱。
- 只提到验证过的只读工具名（`check_symmetry / inspect_model / get_geometry / list_nodes / compare_nodes / get_project_brief / situation_report / screen_space_groups / reflection_statistics / ncs_audit / check_ligand / inspect_map / audit_element_assignment / audit_guest_evidence / audit_heavy_sites / run_checkcif / validate_structure / audit_reflection_data`，均在 `crystalpilot/mcp/server.py` 的 `READ_ONLY_TOOLS` 集合里），对写类工具只用泛称（"任何会修改模型/精修/写入节点或数据的工具"），不点名，这样自然满足 pytest 里"instructions 不得提到任何 `MUTATING_TOOLS` 工具名"的断言，而不是靠事后过滤。
- `developer_instructions` 长度：space_group 768 字、chemistry 768 字、density 734 字、validation 725 字，均在任务要求的 ~1500 字预算内。

**补充事项（不是"决策"，是一个需要有人动手的空档）：这四个角色文件目前对 git 不可见。** `.gitignore` L40-41 写的是：

```
codex-home/*
!codex-home/config.toml
```

注释是"isolated CODEX_HOME runtime state; config is code"——原意是把 `codex-home/` 整体当运行时状态忽略，只把 `config.toml` 这一个手写文件例外放行。`codex-home/agents/*.toml` 四个文件同样是手写的"代码"而不是运行时状态，但现有规则没有给它们开例外：`git status --short` 只会显示 `docs/R7-SUBAGENT-GROUNDWORK.md` 和 `tests/test_codex_agent_roles.py` 两个文件为 `??`，四个角色文件在磁盘上确实存在（已用 `ls -la` 核实，四个文件都在、大小正常），但 `git status --ignored codex-home/` 把 `codex-home/agents/` 整个标成 `!!`（ignored），不加一条例外规则，这四个文件永远不会被 `git add` 捡到，这次的工作会随着 worktree 清理而丢失。本次任务没有把 `.gitignore` 列进允许编辑的文件，所以没有自己去改，只在这里把发现和修法写清楚：需要在 `!codex-home/config.toml` 后面再加一行 `!codex-home/agents/` 加一行 `!codex-home/agents/*.toml`（或者更概括地写 `!codex-home/agents/**`）。

## pytest 结果

```
$ mkdir -p workdir/pytest-tmp
$ H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m pytest \
    tests/test_codex_agent_roles.py -q \
    --basetemp=workdir/pytest-tmp/r7 -p no:cacheprovider
.................................                                        [100%]
33 passed in 1.00s
```

---

## 已验证 vs 未验证

**已验证（有源）**：
1. Codex CLI 版本 0.147.0（二进制 `--version` + 两个 python 包 dist-info，三处一致）。
2. `codex-home/agents/*.toml` 是本项目里"个人级"自定义角色的正确落地位置（官方 subagents 文档 + `CODEX_HOME` 隔离设计）。
3. TOML 必填/可选字段清单（`name/description/developer_instructions` 必填；`model/model_reasoning_effort/sandbox_mode/mcp_servers/skills.config` 可选）。
4. stdio 型 `mcp_servers` 支持 `env` 字面环境变量表（官方 `extend/mcp` 文档，有具体示例）。
5. `spawn_agent` 用 `agent_type` 参数按 `name` 字段匹配角色（`openai/codex#26408` 复现步骤）。
6. `ReasoningEffort` SDK 枚举六档、无 max/ultra，`_missing_` 放行未知值（`v2_all.py` L3204-3219）。
7. `codex.exe features list` 实测：`multi_agent=true`、`multi_agent_v2=false`（与两处既有代码注释里"v2"的表述不一致）。
8. `_mcp_overrides()`（`core.py` L56-90）是**每个 `Workbench` 实例（=每个 app-server 进程）启动时注入一次**的 argv 覆盖，`class Workbench` 的文档字符串原话就是"One app-server process serving one project"（`core.py` L144）。
9. 既有的 `consult_specialist` 机制证明了"MCP 服务器进程读 `CRYSTALPILOT_MCP_READONLY=1` 环境变量、拒绝写类工具"这个只读隔离手段在生产里可行，但它是**另起一个独立的嵌套 Workbench/app-server 进程**（`tools_specialist.py` L226-236 `Workbench(state, ..., mcp_readonly=True)`），不是在同一进程内给原生 `spawn_agent` 出来的子线程做隔离。

**未验证（明确标注,留给主线）**：
1. 本项目实际驱动 Codex 的方式是 app-server JSON-RPC（`Workbench`/`CodexClient`），不是交互式 TUI - `spawn_agent(agent_type=...)` 在这条链路上能否真的解析到 `codex-home/agents/` 下的个人级角色，没有实测（`openai/codex#15250` 曾报告过 tool-backed 会话按名字拉自定义 agent 失败，但那条 issue 已关闭、看不到明确的修复说明；`#26408` 的复现是在独立 CLI 上做的，不是 app-server 模式）。
2. 角色文件里 `sandbox_mode = "read-only"` 是否会被父 turn 当前生效的实时权限覆盖盖回去（b 节引用的官方说法）。
3. 一个角色文件自带的 `[mcp_servers.crystalpilot]` 覆盖（含 `env.CRYSTALPILOT_MCP_READONLY=1`）能不能让子代理线程连到一个**独立于父进程**、真正只读的 MCP 服务器进程,还是会复用/共享父进程已经建立的同名连接，两种可能文档都没提；即使能独立起进程，`args` 里那个 `--project <path>` 必须是具体项目路径，而角色文件是全局共享、写死在 `codex-home/agents/` 下的，这和"一份角色文件服务所有项目"存在张力，本次没有强行拍板去写一个可能是错的 `mcp_servers` 覆盖进四个角色文件。
4. `codex-home/config.toml` 现有 `[agents]` 里的 `max_depth`、`job_max_runtime_seconds` 两个字段，官方文档这次抓取到的 `[agents]` 说明只列了 `enabled / max_concurrent_threads_per_session（别名 max_threads）/ default_subagent_model / default_subagent_reasoning_effort / interrupt_message`，没提这两个。`--strict-config` 能一次性验证这个，但它只对会话型子命令生效（`exec`/`app-server`），本次任务明确不让起会话，留待 R7 实跑时顺手用一次 `--strict-config` 验证。
5. `mcp_servers.crystalpilot.approval_mode`（`core.py` L89 用的裸键名）与官方文档给的 `default_tools_approval_mode`/`tools.<tool>.approval_mode` 对不上，是旧别名还是文档滞后，未查证（没有去动 `.py`）。
6. `"max"`/`"ultra"` 推理档位是否真的存在于网关侧，维持既有代码注释,本次未重新探测网关。

---

## 主线需要做的决策

**决策 1（最核心）：只读隔离到底靠什么落地到 native 子代理。** 现有证据链是：MCP 调用不在 Codex 沙箱边界内（`core.py` 自己的工程注释,外部沙箱文档不否认但也不确认）→ `sandbox_mode = "read-only"` 本身还可能被父 turn 的实时覆盖盖掉（b 节的官方继承说明）→ 真正验证过在生产里管用的隔离手段是 `CRYSTALPILOT_MCP_READONLY=1` 这个 MCP 进程侧环境变量,但它现在的验证前提是"另起一个独立 app-server 进程"（`consult_specialist` 的做法），而 native `spawn_agent` 产生的子线程按文档是**同一个 app-server 进程内**的另一个 thread，不是独立进程。四个角色文件目前只声明了 `sandbox_mode = "read-only"`（prompt 层面 + 这一个可能不牢靠的沙箱声明），没有塞入 `mcp_servers.crystalpilot.env.CRYSTALPILOT_MCP_READONLY=1` 覆盖，因为不确定这样写到底会不会生效、也不确定该不该在全局共享的角色文件里硬编码一个必然要按项目变化的 `--project` 路径。这是 R7 那"一格端到端试验"必须实测才能回答的问题：起一个真项目、真的从主 agent 侧 `spawn_agent` 出一个角色、观察它能不能调用一个写类工具（比如故意问它"帮我 refine 一下"）,看服务端到底拒不拒。

**决策 2：project-scoped 的坑修没修，以及 app-server 驱动这条链路本身通不通。** `#26408` 证明的是"个人级角色在独立 CLI 上能 spawn"，不是"个人级角色在 app-server/JSON-RPC 驱动的会话里能 spawn"；`#15250`（已关闭）当年报告过后一种场景失败。CrystalPilot 的 `Workbench` 走的正是 app-server 这条路，这条路本身是否支持 `spawn_agent` 按名字找到 `codex-home/agents/` 下的角色，需要 R7 那一次真实验来确认，如果不通，四个角色文件和这份文档里关于"怎么选角色"的结论仍然成立，但整个 R7 就得先绕这个更基础的问题。

**决策 3：`[agents]` 里两个未见于当前文档的护栏字段（`max_depth`、`job_max_runtime_seconds`）要不要重新核实。** 如果 0.147.0 已经不认这两个键（静默忽略），现有的"子代理最多嵌套 1 层、单个子代理最多跑 1800 秒"这两条防线就形同虚设，风险等级要重新评估。核实方式建议：R7 实跑时顺手用一次 `codex.exe --strict-config exec ...`（或类似的一次性会话级 dry run）看它是否报未知键；不建议现在为了这一条单独去起会话，因为本次任务明确禁止起交互会话/调用网关。（附带：`e` 节里"`max_concurrent_threads_per_session` 维持 2 还是提到 4"这个更偏工程参数的小选择，建议先维持 2，等 R7 一次实验的真实成本数据出来再说，不单独算一条决策。）

---

## 来源

- Codex 二进制 `--version` / `--help` / `features list`（本次实测,`H:\CrystalPilot\.venv\Lib\site-packages\codex_cli_bin\bin\codex.exe`）
- `developers.openai.com/codex/subagents` → `learn.chatgpt.com/docs/agent-configuration/subagents`（自定义角色位置、TOML 字段、继承规则、`spawn_agent` 选角色方式）
- `developers.openai.com/codex/extend/mcp` → `learn.chatgpt.com/docs/extend/mcp`（MCP 服务器配置字段，含 `env`）
- `developers.openai.com/codex/concepts/sandboxing` → `learn.chatgpt.com/docs/sandboxing`（沙箱边界说明,未提 MCP）
- GitHub `openai/codex#26408`（个人级 vs 项目级自定义 agent spawn 现状,2026-06 开,抓取时仍 open）
- GitHub `openai/codex#15250`（tool-backed 会话按名字拉自定义 agent 的历史报告,已关闭,未见明确修复说明）
- `H:\CrystalPilot\.venv\Lib\site-packages\openai_codex\generated\v2_all.py`（`ReasoningEffort` 枚举 L3204-3219）
- `crystalpilot/workbench/core.py`（`_mcp_overrides` L56-90，`class Workbench` L143-168）
- `crystalpilot/workbench/service.py`（`EFFORT_CHOICES` L82-86）
- `crystalpilot/refine/tools_specialist.py`（`SPECIALTIES` L29-60，`VERDICT_SCHEMA` L62-78，`specialists_enabled` L81-84，`_specialist_prompt` L183-199，`_run_specialist_turn` L203-248）
- `crystalpilot/refine/registry.py`（`MUTATING_TOOLS`）
- `crystalpilot/mcp/server.py`（`READ_ONLY_TOOLS`）
- `codex-home/config.toml`（本 worktree 自己的副本，L23-31，已用 `diff` 核对过与主 checkout 的版本只差主 checkout 后来多出的一条 `[projects.*]` 信任项，`[agents]` 块本身逐字相同）
- `docs/PLAN-2026-09-04-round2.md`（1.2 节、"R7" 节、4 节副线安排、风险清单）
