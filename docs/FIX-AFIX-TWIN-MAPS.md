# AFIX 66、孪晶参数及差值图修复

本次修复三个会影响结构解析判断的问题。代码适用于 Windows 与 Linux；实际测试在 Linux 上完成。

## AFIX 66 导入与精修

原导入器只提取骑乘氢的 AFIX 元数据，非氢芳环的 `AFIX 66` 在第一次节点序列化时丢失。
现在保留刚性组的指令参数、原子成员和顺序，并贯穿导入、节点、改名、导出、SHELXL adopt 和重开项目。
芳环与骑乘氢交错时，使用 SHELXL 自身的 `AFIX 66 → AFIX 43 → AFIX 65` 规则恢复刚性组。
删除导致刚性组不完整的编辑会原子回滚；不支持这些约束的内置精修会明确要求使用 SHELXL。

真实 SHELXL 测试分别验证了三组芳环，以及三组芳环加 18 个骑乘氢，精修后刚性组仍存在、环内边长保持一致。

## 多畴孪晶 BASF

`set_twin` 原先接受 `n=3`，却总是只保存一个 BASF 初值，生成的
`TWIN … 3` 与 `BASF 0.2` 不匹配。SHELXL 会报告
`WRONG NUMBER OF BASF COEFFICIENTS FOR TWIN` 并留下空的 `job.res`。
这是工具的参数构造缺陷，不是 Windows 专属问题，也不能据此否定三畴假设。

### 修复后的参数

- `n=2` 的既有调用保持兼容，省略 `basf` 时仍从 0.3 开始。
- 多畴可传入各分量初值，例如 `n=3, basf=[0.2, 0.15]`，生成两个 BASF。
  第一畴的比例是 `1 - sum(basf)`，此例为 0.65。
- 标量 `basf=0.2` 表示每个附加分量均以 0.2 开始；三畴会生成 `[0.2, 0.2]`。
- 多畴省略 `basf` 时使用等比例初值，每个分量为 `1 / abs(n)`。
- 分量数、初值个数、有限数值及初值总和会在修改模型前检查。
  SHELX 的负偶数 `n`（包含倒反伴畴）仍按 `abs(n)` 个分量处理。

导出器和 `run_shelxl` 也检查 TWIN/BASF 个数，旧的不完整配置会提前得到明确错误。
HKLF5 无 TWIN 的批次比例、无 BASF 的固定等比例孪晶，以及精修后用于诊断的越界比例仍保留。

## 孪晶差值图与补片段

原公共差值图函数把叠加后的观测强度直接当作单畴数据，未使用 TWIN/BASF。
现在 HKLF4 整数孪晶矩阵的各畴结构因子和比例均参与强度分配，使用模型比例去孪晶：

`I_det(h) = I_obs(h) × |Fc(h)|² / Σ α_j |Fc(T_j h)|²`

`fit_fragment`、`inspect_map`、差值密度积分及结构查看器复用此计算。结果记录方法和比例，
并说明去孪晶依赖当前模型；低密度仅表示本图未提供充分放置依据，不证明片段不存在。
旧的查看器地图缓存自动重算；未记录孪晶处理的旧峰表不再作为当前放置原子的依据。

覆盖普通双畴、三畴、含倒反伴畴的负 n，以及各畴溶剂掩膜项。HKLF5、非整数孪晶律、
非物理 BASF 或缺少孪晶相关指数的掩膜系数，会明确返回“密度不可用”，不回退到错误的单畴图。
这些情况仍需使用经过验证的 SHELXL 去孪晶图；本次没有新增 HKLF5 的内部地图算法。

三畴合成数据的完整模型不再产生伪差值峰，补片段测试能恢复缺失的芳环原子。
另以不完美试验模型对照真实 SHELXL `LIST 6` 输出，扣除整体尺度后，去孪晶强度的
总绝对差 / 总强度小于 0.5%；直接使用原叠加强度则超过 5%。

## 另一台电脑如何更新

更新 `codex/linux-workbench-ui-20260909` 分支后，重启 CrystalPilot 服务，使已有
MCP 进程重新载入代码和工具参数。Windows 使用仓库中的
`scripts/restart_server.ps1`；Linux 使用 `scripts/server_linux.py restart`。
本修复不增加依赖，不需要重新构建前端。

GitHub 的该次提交页面会逐文件显示增删内容；需要移植到其他分支时，也可以单独
cherry-pick 这个修复提交。需要一并更新全部修改文件，包括新增的 `crystalpilot/io/twin.py`。
公共差值图还依赖新增的 `crystalpilot/tools/twin_maps.py`，不要只复制单个工具文件。

已经保存的错误试验不会自动改写。继续该试验时，保留原来的孪晶矩阵，重新调用
`set_twin`，明确提供 `n=3` 和两个有物理意义的 BASF 初值，再运行 SHELXL。
修正会生成新节点，旧试验和失败记录保留。初值本身不是孪晶成立的证据。

对于已经丢失 AFIX 66 的旧节点，代码无法凭空推断原约束：请从保留 AFIX 的原始
`DD.res` 重新导入一个独立试验分支，再继续解析；原始数据和既有试验记录保留。

## 验证

新增测试独立生成反射数据，不依赖用户数据或参考结构：

- 修复前，真实 SHELXL 复现了上述 `WRONG NUMBER OF BASF COEFFICIENTS` 错误。
- 修复后，三畴合成强度的已知比例为 0.65 / 0.20 / 0.15；真实 SHELXL 精修
  得到后两个 BASF 为 0.20017 / 0.14991，R1(strong) 为 0.0067。
- 覆盖标量与数组参数、MCP schema、双畴兼容、多畴/负 n、参数拒绝、序列化、
  精修结果读回、旧会话修正及历史节点不变。

Linux 上可运行以下针对性检查；Windows 将 Python 路径替换为 `.venv/Scripts/python.exe`：

```bash
.venv/bin/python -m pytest -q tests/test_twin_components.py tests/test_afix_groups.py tests/test_twin_maps.py tests/test_disorder.py::TestRoundTrip tests/test_twin_suggest.py tests/test_shelxl_tools.py tests/test_swap_data.py tests/test_h_roundtrip.py tests/test_adopt_duplicate_h.py tests/test_data_comparison.py tests/test_fragment_pose.py
```

上述检查结果为 154 项通过、1 项因缺少旧演示数据跳过。
真实 SHELXL 三畴精修、AFIX 刚性组精修和 LIST 6 对照均实际执行。
真实 SHELXL 测试需要本机合法安装的可执行文件，缺失时明确跳过。
已有 `TestSetTwin` 演示数据用例在本次环境缺少 `demo-live-sjtu9/crystal.hkl`，无法初始化；
上述可重现检查使用独立生成的数据。未运行全量后端测试，也未在报告问题的电脑或其 Fe–MOF 数据上验证。
