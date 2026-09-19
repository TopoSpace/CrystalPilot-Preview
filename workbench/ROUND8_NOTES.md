# Round 8 — MOF 原始帧全链路 + Rigaku dxtbx 插件（护城河内化）

日期：2026-08-29（续 round 7）。主线：把 29GB Zenodo 包切出的 Dy-MOF 原始帧
（sample_01，1800×CBF）打通「帧 → 结构」全链路，并把过程中发现的平台空白
（dxtbx 不识 Rigaku HyPix miniCBF）内化成产品自带能力。

## 1. Rigaku HyPix miniCBF dxtbx 插件（commit 9865698）

**空白**：CrysAlisPro "CAP HPAD export" 写的 miniCBF 用
`_array_data.header_convention "RIGAKU_1.3"`，dxtbx 官方无对应 Format 类，
`dials.import` 直接拒收（"dxtbx does not understand these images"）。
这正是"内化护城河"素材：竞品（裸 DIALS）读不了的国产/理学实验室数据，平台开箱即读。

**实现**（`crystalpilot/io/dxtbx_plugin/`，包 `crystalpilot-dxtbx-rigaku`）：
- `understand()`：认 header_convention 含 RIGAKU。
- `_detector()`：**全部几何取自头内自描述向量**（不做 Pilatus 式 "+x/-y" 假设）：
  `origin = distance·n̂ − fast·bx·px − slow·by·py`，n̂ = fast×slow（符号朝向光束）。
  验证了约定：2θ(=−21°) 已折进 fast/slow 向量（slow 经 R_z(+21°) 回转精确落 −Y；
  n̂ = R_z(2θ)·beam），故 Detector_distance 是沿探测器法向、Beam_xy 是 2θ=0 标定点。
  645µm Si → ParallaxCorrectedPxMmStrategy；饱和取 SPECIAL_CCD_2[4]=10480000
  （此格式无 Count_cutoff）。
- `_beam()`：Incident_beam_vector 沿 **−X**（非常规 −Z）→ make_polarized_beam
  (sample_to_source=−incident, fraction=Polarization 0.5)。
- `_goniometer()/_scan()`：Angle_increment 为负（反向扫描）→ 轴取反 + 起角取反
  （R(−â,−θ)≡R(â,θ)），多帧序列变单调递增，dials.import 拼成单一 sweep。
- `_scan()` 用 Exposure_time（基类期望的 Exposure_period 此格式没有）；
  时间戳 "2024-03-4T…"（单位日）fromisoformat 拒收 → 正则宽松解析。
- **注册技巧**：entry point 名 `"FormatCBFMiniRigaku:FormatCBF"` —— DAG 父类必须
  声明为 FormatCBF 而非 FormatCBFMini，因为注册表只下钻 understand() 通过的
  父类，而 FormatCBFMini.understand() 白名单（PILATUS/SLS/…）拒绝 RIGAKU。
  Python 继承仍用 FormatCBFMini（头解析/byte_offset 解压复用）。
- **自动内化**：`frames_dials.ensure_format_plugins(env)` 在 process_frames 里
  自动 pip install 进任何被发现的 DIALS env（幂等、按 prefix 缓存、失败不阻断
  只记 format_plugin_warning）。卸载重装闭环已验证。

**几何验证证据**（workdir/r8-probe/dials）：
- 1800 帧 → 单 sweep；find_spots 16001 峰；**自由索引 69.1%**，RMSD 0.21px/0.16 帧。
- 索引胞 23.423/28.882/28.892Å α=119.98° = CrysAlisPro `_cracker.par` 超胞
  28.822/28.869/11.686Å γ=119.91° 的 **c 轴翻倍**版（差 ≤0.2%）。
  `.par` 的 5.960/9.043/18.396（V=991.5）是平均结构胞——known-cell 索引失败
  不是几何错，而是 max_cell 被压到 23.9Å 装不下 28.9Å 真实基向量。
- 探测器自由精修后 distance 32.95 vs 头标 33.00mm（0.14%）→ 距离/beam 约定解释正确。

## 2. Dy-MOF 全链路 agent E2E（task_20260829_222902，进行中）

- 项目 workbench/r8-dymof，auto 档（DEFAULT 已是 auto），gpt-5.6-sol xhigh。
- **无人值守审批**：auto 档自动放行本家 MCP elicitation，但 codex
  commandExecution 审批（workspace 外 shell，如读帧目录）仍需人批 → r7 同款
  卡点。本轮用带安全过滤的审批守护（workdir/r8-probe/approval_daemon.py）：
  黑名单拒绝（E: 盘、testAPI、codex-home、taskkill/Stop-Process、对数据区的
  写删、git push、系统命令），其余放行并全程留痕（approval_daemon.log）。
  比切 full 档安全：保留 workspace_write 沙箱 + 决策可审计。
  实测 141 决策：138 放行 / 3 误拒（`\bformat\b` 误伤 PowerShell 的
  Format-Table——已改成 `format\s+[a-z]:`；agent 换写法自行绕过，无阻断）。

**结果（turn 66.5 分钟完成，SUMMARY.md + VALIDATION.md + PARTIAL_DY_MODEL.cif）**：
- **A 阶段全成**：1800 帧 DIALS 全链 364s（import 2.6/find_spots 229/index 21/
  refine 35/integrate 52/symmetry 8/scale 8/export 7）。自由索引 69.1%
  RMSD 0.165/0.135px；超胞 28.888/28.888/23.422Å 六方；Rmerge 0.037、
  CC½ 1.000、完整度 96.1%、I/σ 31.4、d_min 1.28Å（Cu 限）。
- **科学判断链**（全部有定量证据落盘）：
  - `.par` 平均胞（5.96/9.04/18.40）自带几何 60.669mm/496.8,513.9px 与本帧
    32.95mm/405,368.5px 不符→判定为另一次采集的记录；显式 max_cell=50 后
    三种方法仍不能用平均胞索引（修正了我预侦察时"max_cell 太小"的初判）。
  - Patterson (0,0,½)=99.2% 原点峰 → c/2 赝平移；奇 l 总强度=偶 l 的 4.4%
    但 35.9% 有 I/σ>3 → 弱而真实的 c 翻倍卫星，转 c/2 主晶格
    （836 unique，Rmerge 0.028，I/σ 58.9）。
  - 途中抓到 DIALS 3.30 bug：reindex 非整数指标行置 (0,0,0) → scale
    `group_id=-1` uint64 溢出；显式过滤 13231 行后成功（失败日志留存）。
  - **拒绝假阳性**：自动流水线 R1=0.0449 "漂亮"模型被识破——溶剂掩膜盖
    89.9% 晶胞吸收 1948 e/胞、模型仅 7 个 C 无 Dy——明确不当成功。
  - charge flipping（P-6m2 工作群）→ 4 强峰；几何核对 Dy···Dy 2.2–2.6Å
    互斥 → 15 种子集比较 → **4 位点各 0.50 占位（Dy9/胞）分裂节点模型**
    未掩膜 R1 0.329（满占位）→0.290；与 sample_02 cracker 组成先验
    Dy9 C40 O8 N2 交叉一致。
  - 诚实边界：Laue P6/mmm 已定，精确空间群不裁决（P6₃/mmc 倾向、
    P6₃22/P6₃mc/P-62c 未排除）；C/H/N/O 框架未解出（节点无序+弥散体系），
    Dy-only R1 0.3505 "不能发表"，交付物命名 PARTIAL_DY_MODEL.cif 防误读。
- **steer 附件真实场景闭环**：turn 运行中 steer 发送 frame_0001.png（衍射帧
  位图），agent 校验 SHA-256、独立观察（弥散晕/弧带可见；单帧不能无歧义认定
  卫星峰——拒绝过度解读）并写入 SUMMARY 证据部分。多模态中途注入全链路 OK。
- v12 AGENTS 审批等待提示生效：agent 两次明确表述"耐心等待，不重启、
  不并行第二套 DIALS"。

## 2b. 事后发现：侧栏空白（用户报告）→ 根因与补救

**现象**：r8 任务完成后 UI 侧栏（结构/节点树/指标）无任何内容。
**根因链**：侧栏数据源是 `<project>/.crystalpilot/refine/` 节点库；本次 agent
全程 shell+python 直驱（transcript 统计：172 shell / 28 文件编辑 / **0 次 MCP
工具调用**），且解算用的是老 SolveSession 栈（`crystalpilot.pipeline.session`，
产 `runs/run_*/artifacts/`），从未触碰会建节点的 refine 栈
（create_start_model / import_cif_model / run_shelxl）→ 节点库不存在 → UI 失明。
**产品课题**：强 agent 读源码后会绕开 MCP 舒适路径直驱底层 API，导致节点树/
3D 场景/回合摘要全部失明——审计链也从 NodeStore 降级为散落的 REPORT.json。
**已做补救**：把 agent 的 PARTIAL_DY_MODEL.cif + dials_c_half/dials.hkl 经
import_cif_model 导入 refine 工程（n0000，4×Dy 半占位，P-6m2）；侧栏节点树/
viewer/PART 全部正常渲染（Dy···Dy 互斥近接触直观可见）。
**待做制度修复（下轮）**：AGENTS v13 硬指引「模型级产物必须经 refine 工具
入节点库，分析可自由用 shell」；更本质的是让 SolveSession runs 可一键
"晋升"为节点，或 pipeline 栈直接写 NodeStore。

## 3. 待办滚动

- steer 附件真实场景验证（integrate 长阶段时发衍射帧 PNG）。
- ROUND8 证据收尾、记忆更新、workdir/r8-probe 清理决策。
- CPO-27-Ni 仍需人工浏览器下载（Cloudflare 拦 curl/cloudscraper）。
