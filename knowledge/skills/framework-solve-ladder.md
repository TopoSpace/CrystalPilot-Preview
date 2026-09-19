---
name: framework-solve-ladder
description: 大胞/弱衍射框架结构的求解失败阶梯：SHELXT 默认 → -y/-a → -m1000 → -d 逐级截断 → 换 unmerged 数据 → 电荷翻转（内置 solve_charge_flipping / 外部 solve_superflip 双引擎）→ 金属子结构+差傅立叶。含各引擎适用边界（SHELXT 不吃严重无序/孪晶；电荷翻转要求高完整度；直接法 1.0-1.1 Å 失效、双空间可到 1.5 Å）与 superflip 判读要点（全分辨率纪律、对称一致性因子、对映体随机）。run_shelxt 首跑失败或 CFOM 全线难看时读此卡。
alerts: []
tools: [run_shelxt, solve_charge_flipping, solve_superflip, estimate_resolution, ingest_vendor_data, fourier_complete, add_atoms_from_difference_map, interpret_peaks]
tags: [求解, SHELXT, 电荷翻转, 分辨率截断, 金属亚晶格, 弱衍射]
source: SHELXT 官方开关文档 (http://shelx.uni-goettingen.de/shelxt_keywords.php)；Sheldrick, Acta Cryst. A71 (2015) 3-8 (https://journals.iucr.org/a/issues/2015/01/00/sc5086/)；Palatinus & Chapuis, J. Appl. Cryst. 40 (2007) 786 (SUPERFLIP)；Müller, Crystallogr. Rev. 15 (2009) 57-83 (https://web.mit.edu/pmueller/www/own_papers/suggestions.pdf)；Olex2 solve 文档 (https://www.olexsys.org/olex2/docs/tasks/tasks/structure-solution/)
confidence: high
created_by: researcher
---

# 框架求解失败阶梯

## SHELXT 行为模型（决定阶梯设计）

- 数据展开 P1 双空间迭代（Patterson 叠加起相+随机 omit），P1 相位回推
  Laue 群内所有群，按 CFOM = CC − α·R(weak) 排序。**系统消光不参与定群，
  弱反射全程参与鉴别正确解**：求解阶段同样不要预删弱反射。
- 缺失数据自动外推补全（-e "free lunch"，默认到 max(0.9, d−0.1) Å）。
- 自认边界：**不适合严重无序与孪晶**；大等原子/孪晶结构 SHELXD 类更强。
- 元素表陷阱：解出未申报的重元素时会擅放 Br/I 占位，金属元素必须如实
  进 SFAC/分子式，看到莫名卤素先怀疑元素表而不是化学。
- **两段执行，第二段通常更长**：先 P1 双空间定相（日志 `Structure
  solution: N secs` 标记该段结束），再把最佳解放进 Laue 群内每个候选
  空间群逐一精修比较。**超时几乎都发生在第二段**：大胞高对称尤甚
  （r25 的 6/mmm、39.2×39.2×16.6 Å：定相仅 62 s / 24 s，随后被 180 s
  与 120 s 的超时砍在群搜索里）。第二段没跑完就没有任何 .res 产出，
  所以"超时"读起来像"求解失败"，其实相位早已到手。判读要点：
  **看日志里定相段是否已完成，再决定是加时重跑还是换引擎**。
- **timeout_s 只限制定相段（2026-09-02 起）**：定相一旦完成，群搜索自动
  获得 `search_grace_s`（默认 900 s）宽限，不会再被砍；运行中每 20 s 有
  进度通知（已完成 try 数、best CFOM、当前录取线、每 try 秒数；或"定相
  已完成，群搜索进行中，宽限剩余 N s"）。超时消息带 try 表判决：SHELXT
  的录取规则是 CFOM > x + 0.01·max(20−m, 0)（x 默认 0.65，即录取线从
  第 1 try 的 0.84 逐 try 降到第 20 try 起的 0.65），best CFOM 已在
  0.65 之上：**加大 timeout_s 就能收**；best CFOM 在 0.65 之下：加时
  只是重复同类 try，**改搜索而不是改预算**（solve_resolution 砍噪音壳、
  composition 如实申报重原子、chem_quality 开/关、space_group= 限定）。
  pa1 实测：hex（22 000 Å³、6/mmm）定相 150–840 s、群搜索 300 s、
  元素指认 90 s；cage（19 000 Å³、2/m）定相 110–830 s。
- **预算按作业自己的 try 表算（2026-09-03 起）**：SHELXT 一批跑 -t 个
  try（-t = 线程数），每批把每 try 的迭代数 ×1.46，末批最贵，通常 16–20
  个 try 才录取，预算 ≈ 20 × 每 try 时间。**n_phase_sets（-m）是每个
  try 的迭代数**，加大它只会让每个 try 更慢、下一次被杀得更早（pa2 三格
  cage 的求解就是这样丢的：-m300/600/1000 全部超时，-m100 都在 70–150 s
  出解）；>500 钳到 500，**绝不加大**。被杀的作业没有 .res，不能续跑。
  超时消息里的 `suggested_timeout_s` / `suggested_n_phase_sets` 就是下一次
  的参数，只许照它加 timeout_s 或减 n_phase_sets。
- **过线的作业不再被杀**：best CFOM 已过录取线时 `phasing_grace_s`
  （默认 600 s）按估计剩余时间自动延长，心跳里写"已过线，预计 try M，
  约 y s，延长 z s"；未过线仍按 timeout_s 杀。
- **大胞不要阻塞等**：`run_shelxt(detach=true)` 立即返回 job/pid/
  progress_json → 每 60–120 s `run_shelxt(job_status=<job>)`（立即返回
  stage/tries_done/best_cfom/预计剩余，不占锁）→ stage 为 finished 后
  `run_shelxt(from_job=<job>)` 采纳。阻塞调用期间可用 shell 读作业目录的
  `progress.json`（每 20 s 更新），不要读 job.lxt 尾部猜进度。同一项目
  同时只跑一个 SHELXT。
- `space_group='P 21'`（SHELXT -s）只在指定群里解：群已定、或 SHELXT
  总把非心子群判回中心对称母群时用；`from_job='job_2026…'` 直接采纳
  一个已完成 job 的解而不重跑（跳过采纳后想回头、或上一会话的 job）。
- **`-a` 会被 SHELXT 自己打开**：只要元素表里有比 Sc 重的原子，日志会
  出现 `-a set to extend space group search because atom heavier than
  Sc expected`。含金属结构里 `all_space_groups=false` 因此**不是提速
  手段**（r25 第二次重跑就栽在这个假设上：以为缩小了搜索范围，同时把
  超时从 180 s 砍到 120 s，实际工作量一点没少）。

## 什么时候不该再回求解阶梯（pa2 教训，2026-09-03）

- **模型已经立住（金属节点对、连接体长出、R1 明显低于 0.25 且在下降）
  之后不再回求解阶梯**：此后的问题是模型完整性（缺原子、元素、掩膜、
  无序）的问题，重新求解只会把已有的进展扔掉再跑一遍同样的 try。pa2 的
  cage 格在 R1 0.17 时又去跑 SHELXT -m600/-m1000，两次超时，把两小时和
  一个正确的骨架一起丢了。
- **同参数重跑给出相同的 CFOM 序列（pa2 实测），说明相位集没有变**：
  重跑不会得到新解，改一个变量（分辨率、组成、-y/-a、空间群限定）再跑
  才有意义。

## 失败阶梯（逐级升级，每级只动一个变量）

1. 默认参数跑（unmerged 数据优先；SHELXT 对 Flack>0.5 的解自动翻转）。
2. `-y`（Chem×CC 品质因子，键角 95-135° 判据；适合金属有机框架，
   **纯无机不适用**）与 `-a`（强搜 Laue 群内全部空间群，覆盖 α-gap 判群
   失误；-a 覆盖 -g/-h/-w）。
3. `-m1000`（P1 迭代 100→1000）：专治 "CC 尚可但解一团糟" 或全部 CC<0.87。
4. `-d` 逐级截断噪音外壳（官方建议 problem structures 用 stepwise
   truncation；默认 -d0.8）。**求解可比精修截得更狠**：先用截断数据拿
   相位，终修换回全数据。
5. 换求解引擎：电荷翻转（对称性无假设、无需元素先验，赝对称/组成不明时
   反而更稳；但**要求高完整度与分辨率**，数据烂时别指望）。完整度边界
   已有实测：**≤55% 完整度上 6 次尝试 0 成功**（r16 净化子集 22% 两次
   超时 9 min；r18 55% 两次超时 14 min；r13 主畴近似 3 败 10 min，
   create_start_model 的 "no phase transition" 三投三现同因）。粗线：
   完整度 <~70% 时先别投电荷翻转，把预算给 SHELXT 阶梯或差傅立叶；
   真要试也只试一次短超时，超时即停不加时重跑。两条实现互为
   交叉验证：solve_charge_flipping（cctbx 内置）与 solve_superflip
   （外部独立引擎，判读要点见下节），两引擎在同一空间群下给出一致峰型
   时置信度大增；只有一个成功也完全可用。**solve_superflip 在 2026-09-02
   之前的全部超时（r16→pa1 共 17/17）都是启动缺陷（子进程继承了 MCP
   的 stdin 管道而卡死），不是数据证据；修复后同一份 hex/cage 输入
   15–30 s 收敛。它的超时消息若说 "never started computing"，按环境
   故障重试一次并报告，不要据此换路线。**
6. 金属子结构先行：Patterson/重原子峰先定金属节点（对照已知 SBU 几何
   核对合理性），几轮精修后差傅立叶逐步长出配体（fourier_complete +
   interpret_peaks 迭代；每步收敛再走下一步，可疑峰宁缺勿滥）。
7. P1 兜底：中心对称群解不出常在 P1 一解就出；解出后必须找回对称元归位
   正确群，P1 是工具不是归宿。

## solve_superflip 判读要点（实测教训，Zn-MOF P2₁2₁2₁ 实据）

- **全分辨率纪律（与 SHELXT 相反！）**：阶梯第 4 级的 -d 截断策略只适用
  SHELXT；superflip 对 d_min 截断极端敏感，同一数据全分辨率对称一致性
  因子 0.11，截到 1.1 Å 恶化到 0.76（不可用）。跑 solve_superflip 一律
  d_min=null 全数据，除非明确要排除坏外壳。
- **对称一致性因子 = 密度空间的空间群独立判据**：per_operator 逐算符 +
  overall 总值，<~0.25 视为该对称元真实存在于密度中，这比消光统计更直
  接（消光只看倒空间零层，一致性因子看整个密度）。用它交叉验证
  scale_and_export 阶段的定群结论；某个算符单独很差 → 怀疑赝对称或定群
  过高。
- **对映体随机**：电荷翻转每次随机落在两个对映体之一，手性到 Flack 阶段
  才定，解出后与任何参考/预期比对时必须模掉反演与允许原点移位（欧几里
  得规范化群平移，如 P2₁2₁2₁ 有 8 个半胞移位），否则"看着差半个胞"是
  假警报。
- **可复现性**：randomseed 参数固定种子可复现同一解；默认引擎自选。
- **引用义务**：superflip 求解进入发表流程时必须引用 Palatinus &
  Chapuis, J. Appl. Cryst. 40 (2007) 786-790（工具 summary 自带提醒）。

## 分辨率与方法边界（预期管理）

| 数据分辨率 | 可用方法 |
|---|---|
| ≤1.0-1.1 Å | 经典直接法尚可 |
| 1.1-1.5 Å | 双空间法（SHELXT/SHELXD/电荷翻转）主场 |
| >1.5 Å | 纯 ab initio 基本无望，走拓扑先验建模+局部精修混合路线 |

## 全阶梯失败后

- 回数据端：变温重测（高孔隙 MOF 可能室温更好，见 mof-data-collection-
  bottomline 卡）、重选晶体、查孪晶警示征（见 framework-twin-
  pseudosymmetry-alarm 卡），求解失败常是数据病而非算法病。
