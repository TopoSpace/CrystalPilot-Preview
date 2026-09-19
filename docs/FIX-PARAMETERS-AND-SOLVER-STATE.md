# 保持约束的参数编辑与求解状态修复

本次补齐三个公开模型编辑入口，并修复电荷翻转预算、空模型空间群声明的持久化。
不需要移除已有 AFIX/TWIN 来完成金属 ADP 或占有率试验。

## 指定原子的 ADP 转换

调用 `set_adp`：

```json
{"atoms":["FE","FE00","FE1","FE04"],"mode":"anisotropic"}
```

只转换这些原子的表示，使用与原 Uiso 等价的张量，并投影到相应特殊位置的对称约束。
坐标、占有率、元素、其他原子的 ADP、AFIX、TWIN/BASF 和 FVAR 链接保持原状。
操作保存新节点；这一步不是数值精修。随后调用 `run_shelxl(mode="adopt")` 进行真实精修。
`mode="isotropic"` 可用于反向比较。骑乘氢的 ADP 仍由载体约束管理，不会被静默替换。

`run_shelxl.extra_cards` 里的 ANIS 仍会被拒绝，但明确指向此入口。
`refine(n_cycles=0)` 或无独立自由参数的请求会返回明确的不适用说明，
不再进入空数组求解。仅计算指标可用 `run_shelxl(mode="check", l_s=0)`。

## 单点固定/自由占有率

调用 `set_site_occupancy`：

```json
{"atom":"FE04","mode":"free","value":0.5}
```

`value` 是实际占有率，不是 SHELX SOF 编码。工具为该单点分配独立 FVAR，
SOF 乘数按特殊位置的多重度处理。例如二重特殊位置上的 0.5 占有率使用
`FVAR 1.0 0.5` 与 `SOF 20.5`，而不是把 20.5 当作占有率。

随后运行 SHELXL，`site_occupancies` 返回实际占有率、换算后的 s.u.、Ueq、
SHELXL 报告的占有率–ADP 大相关项，以及相关性覆盖范围说明。
零周期未提供 s.u.、或 s.u. 小于列表打印精度时，不报告成“精确为零”。
adopt 节点保留带作业来源的 FVAR 测量信息，聊天摘要显示占有率及其 s.u.。

用 `mode="fixed", value=1.0` 或 `value=0.5` 建立全占/半占候选。
建议在独立分支分别精修并比较对应节点。固定某个单点后，其他 FVAR 的编号与物理含义
会保持对应；共享无序变量、SUMP 链接不会被单点操作静默拆开。
占有率、U、尺度可能高度相关，R 较小不能单独确定元素或精确组成。

## 非氢 AFIX 编辑

调用 `set_afix`，支持 `action="list" / "create" / "replace" / "remove"`。
`group_index` 为 list 返回数组的零基下标；同时可使用通用的 expected_node /
expected_project_revision 前置条件。

- `afix=66`：六元环，原子列表必须按环键循环排序。检查近似平面性与现有键长。
- `afix=6`：按已有几何建立一个完整刚体；可用于已经接受的完整融合蒽核。
  全部 14 个骨架原子各列一次，共享融合原子不能重复进入三套六元环约束。
- `replace` 用新组替换所选旧组，`remove` 删除所选约束而保留原子。
- 检查重复/缺失原子、其他组的重叠、PART、连通性及共线性。
  在特殊位置上新建通用刚体会明确拒绝，因为需要专门的受限运动模型；已有导入约束仍可保留。

下面仅为接口示例，必须换成当前模型中已经得到支持的真实原子标签：

```json
{"action":"create","afix":66,"atoms":["C1","C2","C3","C4","C5","C6"],"reason":"已接受的外接芳环"}
```

AFIX 编辑不生成、补齐或移动原子，也不提供新的密度证据。缺失候选仍须通过
`fit_fragment` / `accept_fragment_pose` 等数据支持检查。完整蒽核尚未接受时，不能用此入口制造它。
创建/替换后的约束贯穿节点、SHELXL adopt、checkout、rename 和交付。
AFIX 6 的刚体语法参照 [SHELXL AFIX 手册](https://shelx.uni-goettingen.de/shelxl_html.php?command=AFIX)，并经过真实 SHELXL 验证。

## 电荷翻转预算

原实现主要在迭代器每十步 yield 时看时钟；初始化和原生单步不可中断，峰提取又在预算上下文之外。
现在由父进程监督独立计算 worker，预算覆盖输入序列化、worker 启动、预处理、初始化、
原生迭代、Fourier/峰提取及结果读取。即使某一步不让出 Python 控制，也可以中止该 worker。
最多额外留 2 秒用于回收；项目锁排队等待不计入计算预算。因此请求 55 秒对应最多约 57 秒的
计算及回收窗口。中断不发布半成品，不改变原有模型或峰表，也不需要手工杀进程重试。

`timeout_s` 是规范参数；`time_budget_s` 作为兼容别名。
`max_solving_iterations` 的兼容别名为 `max_iterations`。同义参数值冲突会被拒绝。
返回总 elapsed_s、预算覆盖范围、最后阶段及已得到的迭代信息；取消请求也会回收该调用自己的 worker。

## 空模型的空间群声明

原代码只修改内存和部分启动文件，却返回 `no_state_change=true`，没有保存模型节点。
下一次失败触发节点回滚，就重新载入旧空间群。

现在会同步建立新空间群的空模型、重新合并反射数据并保存声明节点。
原始输入不改写，数据版本保持绑定；失败、下一次调用及重新打开均读取该声明节点，
显式 checkout 仍可回到原空间群。这是声明的持久化，不代表数据已经证明该群。

## 更新与验证

更新 `codex/linux-workbench-ui-20260909` 分支，在 `ui` 中运行 `npm run build`，
再用原有服务脚本重启 CrystalPilot。Python 无新增第三方依赖，计算 worker 使用当前项目的 Python。
Windows 使用 `scripts/restart_server.ps1`；Linux 使用 `scripts/server_linux.py restart`。
重启使 MCP 重新加载新增工具；工作台生成的项目指令也包含这些入口。

测试使用独立合成数据和本机合法安装的 SHELXL，覆盖：

- 四个指定 Fe 的转换与其他参数不变，特殊位置的 Uij，SHELXL adopt 后 RES/CIF 对账。
- 单点特殊位置的自由占有率及 s.u.，全占/半占对比，多 FVAR 编号对应与相关性读回。
- 六元环创建、完整融合核替换、重叠/缺失/PART 等拒绝，真实精修及交付。
- 初始化、原生迭代、峰提取和结果序列化的阻塞、取消、实际计算 worker 返回。
- “声明 → 失败 → 下一次调用 → 重开 → checkout”的完整状态链。

本次针对性回归：274 项通过，1 项因旧演示 HKL 数据缺失跳过；前端 12 项通过，构建通过。
新增功能的核心复查可运行（Windows 将 Python 路径改为 `.venv/Scripts/python.exe`）：

```bash
.venv/bin/python -m pytest -q tests/test_parameter_edits.py tests/test_afix_editor.py tests/test_solver_state_budget.py
```

未在另一台电脑的原始项目上操作，也未替代后续金属、对称性、配体姿态或无序检验。
