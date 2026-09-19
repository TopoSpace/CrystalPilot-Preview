---
name: framework-twin-pseudosymmetry-alarm
description: 孪晶/赝对称警报链：Herbst-Irmer & Sheldrick 警示征证据清单（|E²-1| 偏低、双 Laue 群 Rint 接近、度规高于 Laue 对称等，证据累积制，多条同向才构成强怀疑）；高对称框架孪晶高发先验；孪晶假设与空间群竞争并行的低成本诊断顺序；漏反演中心症状（等价键长大幅波动而均值正常）；BASF≈0.5+整体无序→查超胞。数据难索引、解不出、R 卡高位、或 ADDSYM/换群争议时读此卡。
alerts: []
tools: [audit_reflection_data, set_twin, change_space_group, run_shelxt, run_shelxl, ingest_vendor_data]
tags: [孪晶, 赝对称, 超胞, 空间群, E统计, 警示征]
source: Herbst-Irmer & Sheldrick, Acta Cryst. B54 (1998) 443-449 (https://journals.iucr.org/paper?S0108768197018454=)；Herbst-Irmer《Twinning in chemical crystallography - a practical guide》讲义 (https://cdifx.univ-rennes.fr/RECIPROCS/Paris2019/pdf/ChemicalCrystallography_RHI.pdf)；Olex2 twinned 文档 (https://www.olexsys.org/olex2/docs/tasks/tasks/twinned-structures/)；Zr-MOF 孪晶专文, Chemistry 2 (2020) 50 (https://www.mdpi.com/2624-8549/2/3/50)；Müller, Crystallogr. Rev. 15 (2009) §3.4/§4.4；赝缺面孪晶案例集 Acta Cryst. E77 (2021) (https://journals.iucr.org/e/issues/2021/05/00/hb7973/)；Zanuda, Acta Cryst. D70 (2014) 2430
confidence: high
created_by: researcher
---

# 孪晶/赝对称警报链（框架）

## 先验：框架是孪晶高发区

Zr-MOF 专项研究证明孪晶在某些框架中"高发甚至不可避免"，发现的孪晶法则
可推广到同拓扑网络；MOF 晶体中还频繁出现"任意旋转矩阵关联的互生多畴"
（非严格孪晶）。高对称大胞 + 立方/四方/三方度规 = 默认怀疑对象。
（NU-1100 判例：XPREP 初判 Im-3m 是被孪晶蒙蔽的表观群。）

## 警示征清单（证据累积制：单条命中值得低成本排查并记录，多条同向才构成强怀疑；数据摄入时可算的前三条应自动化）

1. |E²-1| 显著偏低：理论值中心对称 0.968 / 非心 0.736；掉到 ~0.8/~0.6
   即疑（XPREP 惯用 <0.68 报警）。
2. 高低两个 Laue 群的 Rint 接近（真群应显著更低；多晶体同低群 Rint 相似
   而高群分散 = 强证据）。
3. 度规对称高于衍射 Laue 对称（单斜 β≈90° 假扮正交等）。
4. 难索引/劈裂斑/异常长轴。
5. 消光条件对不上任何已知群；求解全线失败；Patterson 物理不可能。
6. 精修期征兆（旗标而非裁决）：R 卡高位、权重方案第二参数居高不下
   （>5 为经验旗标锚点）、弱反射 Fo²≫Fc²（K 值异常），各有备择解释
   （弱数据/吸收/模型缺块同样抬高这些量），组合同向才加重孪晶怀疑。

## 处置顺序（成本不对称原则）

**低成本诊断先行、并行摆证据，再做贵的改模**：找孪晶矩阵（TwinRotMat/
ROTAX 类外部算法；平台内 set_twin(law='suggest') 列出度规允许的候选律）
和空间群竞争核查（`screen_space_groups` 工具，消光+E 统计榜，厂商 hkl
路线无原子会话即可用；帧路线 scale_and_export 的 space_group_screen 字段
是同一张表）都只需几分钟，应先于花几天拆无序，先拆无序会把孪晶信号建模成假
无序；孪晶与错群/超胞是同一批症状的竞争解释，按证据对照检验而非固定
顺序（与 data-ingest 卡"错群哨兵先查群"一致，改群贵在推倒重修，查群
本身不贵）。孪晶法则候选找到后**尽早试精修**（set_twin → run_shelxl
对照），裁决看证据组合：BASF 收敛离 0 **且** R/差图/椭球实质改善 **且**
法则有衍射学来源（度规/警示征/帧证据）= 第二域假设得到支持；BASF 离 0
但指标不动、或法则无来源，则可能只是吸收了系统误差，与无孪晶模型
对照后再下结论。HKLF5 数据走 hklf5-twin-workflow 卡。

## 赝对称判据

- **漏反演中心症状**（P1/低群误留）：等价键长键角大幅波动而**平均值正常**
  （判例：芳环 C-C 1.324-1.465 Å、均值 1.39）；椭球形状方向乱跳；s.u.
  偏大。强限制能"救活"表观质量但属饮鸩止渴，唯一解法是归位正确群，
  归位后无限制模型全面更优且 R 几乎不变。
- **反向陷阱**：被指"应为更高对称"时，诚实试解/精修高对称群，收敛失败
  本身就是保留低群的证据（Zanuda 思想：候选群集合逐一精修裁决，而非
  只看 ADDSYM 的几何判断）。
- **超胞怀疑链**：BASF≈0.5 + 整配体"无序" + 大量 OMIT → 先查晶胞轴翻倍
  /降群，再考虑孪晶法则；弱超胞反射靠保留弱数据才能看见。ADDSYM 建议
  的高对称群要与"孪晶+低群"备择假设对照检验（判例：ADDSYM 报 P2/n，
  真相是赝四方 I2/a 超胞的四组分孪晶）。

## 纪律

- 宣称"无孪晶"是证据陈述而非默认状态：警示征逐条核查无同向证据，且
  Flack 侧**有判定力**（su 足够小+Parsons/classical 一致+反常信号足够
  强，见 flack-absolute-structure 卡）且不指示反演孪晶时，方可下此
  结论；su>0.3 的"Flack 正常"无判定力，**不能**用于排除孪晶，此时
  如实写"未发现孪晶证据；反演孪晶因反常信号弱不可判"。个别警示征命中
  但已按竞争模型排查并记录的，披露排查过程即可下结论，不因单条旗标
  扣发。
- 换群/加孪晶后所有派生结论（Z、分子式、无序分组、Flack）重新核对。
