---
name: framework-restraint-idioms
description: 框架/无序精修限制惯用法与 SHELXL 默认 s.u. 表：SADI 0.02/0.04、DELU 0.01、RIGU 0.004、SIMU 0.04（端基 0.08、自由旋转基团禁用）、ISOR 0.1/0.2（全局仅最后手段，局部档位见表），均为来源明确的起点锚点，按数据/阶段调节、每条留理由并做撤除测试；无序精修为何几乎总需相似性限制（参数强相关的数学理由）与"拆位同步上限制"实践；分步拆位流程与 EADP 正当场景（EADP/EXYZ 当前平台不可执行，标外部）；lst 的 most disagreeable restraints 作为限制健康度回读。model_disorder/set_restraints 之前、或被批 over-restrained 时读此卡。
alerts: []
tools: [set_restraints, model_disorder, run_shelxl, add_hydrogens, edit_atoms, validate_structure]
tags: [限制, SADI, SIMU, RIGU, EADP, ISOR, 无序精修]
source: Müller, Crystallogr. Rev. 15 (2009) 57-83（数值表全文核对, https://web.mit.edu/pmueller/www/own_papers/suggestions.pdf）；Müller 无序精修教程 (https://web.mit.edu/x-ray/Summer_School_Material/Disorder_Workshop/Disorder_Workshop.pdf)；DSR, J. Appl. Cryst. 48 (2015) (https://journals.iucr.org/j/issues/2015/03/00/fs5104/)；CCDC 教学 (https://www.ccdc.cam.ac.uk/media/resources/schaper-disorder-fs06a.pdf)；MOF SI 实践（HIAM-402x 等, ACS Inorg. Chem.）
confidence: high
created_by: researcher
---

# 限制惯用法（框架/无序）

## 两条实践基线（有数学理由，但不免论证）

1. **无序精修几乎总需要相似性限制**：无序分量在空间平均中互相重叠、参数
   强相关，几何+ADP 相似性限制有数学必要性（不是美容）。但"需要"≠
   "免论证"：每条限制写明对象与理由（对应 set_restraints 的先验声明
   语义），收敛后做撤除测试，撤后指标/椭球维持则可撤或作为已验证先验
   披露保留，恶化则说明模型依赖先验，交付时如实说明。
2. **拆位与限制同步上**（restraints as you go）：拆位的同一步就上限制；
   "先拆开看看再说"常见翻车。可先紧后松，稳定后放松或撤销，"上得早"
   与"稳定后撤"（disorder-ruleset 三-10 脚手架）是同一流程的两端。

## 数值表（SHELXL 默认/惯用 s.u.：来源明确的起点锚点而非免检配方：先诊断参数病态与相关性再选指令与强度；限制多于参数不丢人，但每条要有理由）

| 限制 | 起点 σ（来源） | 适用 | 禁忌 |
|---|---|---|---|
| SADI/DFIX 键长 | 0.02 Å（SHELXL 默认） | 等价 1,2-距离 | 优先 SADI（不引外部目标值）；DFIX 目标可取 CSD 均值 |
| SADI 1,3-距离 | 0.04 Å（同 DANG 默认） | 角的等价表达（SHELX 无角限制） | — |
| FLAT | 0.1 Å³（SHELXL 默认） | 芳环/羧酸平面 | — |
| DELU | 0.01 Å²（SHELXL 默认） | 成键原子沿键 ADP 相等（Hirshfeld）；低分辨率时可全结构上 | 物理最稳，基本无禁忌；旋转基团也适用 |
| RIGU | 0.004 Å²（SHELXL 默认，比 DELU 紧；与 disorder-ruleset 四-3 同源） | 增强刚性键（每原子对 3/6 条），常可替代 DELU | 各向同性原子上被忽略（此时用 SIMU） |
| SIMU | 0.04 Å²（端基 0.08，SHELXL 默认） | 空间邻近原子（<1.7 Å）ADP 相似 | **自由旋转基团（CF₃/硫酸根类）禁用**；各向同性阶段就可挂上（转 anis 后自动生效） |
| ISOR | 0.1 Å²（端基 0.2，SHELXL 默认） | 近各向同性化 | **全局使用是最后手段**（典型：大结构自由水）；局部病态椭球语料有更紧档 0.01/0.02（tid 1891/20181228，见 disorder-ruleset 四-4）；严禁当椭球美容术，病态椭球必须先查因（孪晶/元素/占据/吸收） |

- σ 语义：SHELXL 限制以 target±σ 计入最小二乘，σ 越小权重越大、限制越强；
  按数据质量（分辨率/冗余/I/σ）、无序类型与精修阶段调节，偏离默认要记录
  理由；收敛后做撤除测试并在交付中披露保留的限制。

- 弱衍射大空隙框架的 SI 常见组合：SIMU + DELU/RIGU 全局 + DFIX/SADI 键长
  （"not uncommon for this kind of framework"），这是文献惯例观察而非
  默认配方：先确认病态证据（椭球发散/参数相关/数据参数比），按需逐条加
  并留理由；重度无序才叠 DANG/ISOR。

## 约束（constraint）的位置

- 约束是刚性方程，用错伤害大于限制，几何稳定优先用限制。
- EADP 正当场景：共享位点双元素（EXYZ+EADP）、CF₃ 两分量"对位 F"配对、
  刚体内部。**大面积 EADP 让结构"看起来还行"= 掩盖无序**，审稿会点名；
  撤掉不当约束常反而降 R。**外部能力**：EADP/EXYZ 当前 set_restraints
  （仅 DFIX/DANG/SADI/FLAT/SIMU/DELU/RIGU/ISOR）与 edit_atoms 均不支持，
  属外部 SHELXL 指令需人工执行；平台内最接近的替代是 SIMU 软限制
  （review-response-ruleset A14 同判：非 EXYZ 共位场景优先 SIMU）。
- 完全弥散但几何已知的基团（高氯酸根/苯溶剂）可整体刚体（6+1 参数）代替
  3N 参数。

## 分步拆位流程（可判据化）

1. 从无序最明显的末端 2 原子拆起（PART 1/2 + 自由变量占有率，和固定 1）；
2. 全程各向同性 + SADI/SIMU，逐步向根部扩展拆位范围；
3. 稳定后整体转各向异性 + RIGU；最后加 H（H 跟随载体 PART）；
4. 多处无序一次修一处；无序范围很大时分片推进，语料经验量级在约 20%
   独立原子，但以每步收敛质量与参数相关性为准，不以固定比例切换工作流。

## NPD（非正定）椭球的处置顺序（pa2 教训，2026-09-03）

- 转各向异性后出现 NPD / 椭球发散，**第一步是全模型上 RIGU（或 DELU）+
  SIMU 再精修一轮看是否收敛**，不是退回各向同性。pa2 的 cage 格把
  "NPD → 退回 isotropic → R1 变差 → 掩膜不稳" 连成了一串，根源是第一步
  就走错了。
- 只有在刚性键限制下仍 NPD 的原子才逐个查因：元素太重/太轻（Ueq 与邻居
  比）、占有率不足（部分占有的溶剂/客体）、位点错（差图正负对峰）、孪晶
  或吸收。局部 ISOR 是这些都排除之后的最后一档，并留理由。
- 退回各向同性是**披露项**而不是默认：交付里写明哪些原子为何各向同性。

## 健康度回读

- 每轮精修回读 lst 的 **most disagreeable restraints** 表：目标值与精修值
  大差 = 限制被数据推翻，要么该限制不成立（撤/换），要么模型有更深错误；
  不许无视。
- 被批 over-restrained 的自查序：去重（SAME/SADI 重复覆盖）→ 降强（放大
  σ）→ 逐条留存理由（对应平台 A13）。
