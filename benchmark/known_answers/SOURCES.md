# `benchmark/known_answers/`：已知答案对照数据

为验证 `crystalpilot/chem/interactions.py` 而单独下载的公开结构。每个条目都带
作者自己沉积的 `_geom_hbond_*` 表（已知答案），下载自 Crystallography Open
Database（COD，公共领域/CC0 元数据；单条结构的版权与引用见下）。

下载命令（本机 2026-09-05 执行，可复现）：

```bash
curl -s -m 60 https://www.crystallography.net/cod/<COD-ID>.cif \
  > benchmark/known_answers/<slug>/ref.cif
```

## `xb_tfib_bipy_cod2201150/ref.cif`

- COD ID: **2201150** — <https://www.crystallography.net/cod/2201150.html>
- 化学式：`C16 H8 F4 I2 N2`（4,4′-联吡啶 · 1,4-二碘四氟苯 共晶）
- 空间群 `I 1 2/a 1`，a=14.2535(10) b=33.714(3) c=14.3511(12) Å，T=290(2) K
- 期刊：Acta Crystallographica Section E (2002)，doi `10.1107/S1600536802007201`
- 已发表 R1(gt) = 0.0385
- 为什么选它：这是卤键（C–I···N σ-hole）的教科书共晶，同时沉积表里有 5 条
  C–H···F 行，可以同时检验 `halogen` 与以 F 为受体的 `chx` 两种类型，本仓库
  原有 13 个基准结构里没有一条通过判据的卤键行。
- 许可：COD 数据按 COD 条款提供（IUCr 期刊数据，科学共同体内自由使用，需引用
  原文）。

沉积的 `_geom_hbond_*` 表（原文照抄，作为已知答案）：

```
C2C H2C F1B 6_655 0.94(2) 2.54(4) 3.452(7) 165(4)
C5C H5C F3A 5_555 0.92(2) 2.68(3) 3.557(7) 160(3)
C6C H6C F4B 6_555 0.93(2) 2.44(4) 3.342(7) 165(3)
C2D H2D F1A 7_554 0.93(2) 2.69(4) 3.597(7) 167(3)
C6D H6D F4A 7_555 0.92(2) 2.46(4) 3.313(7) 154(3)
```


## `anionpi_triazinium_bf4_cod2232050/ref.cif`（第三轮 R5-F 下载，2026-09-06）

- COD ID: **2232050** — <https://www.crystallography.net/cod/2232050.html>
- 化学式：`C4 H8 B F4 N5`（2,4-二氨基-6-甲基-1,3,5-三嗪-1-鎓 四氟硼酸盐）
- 空间群 `P -1`，a=6.9982(3) b=8.2887(4) c=8.5353(4) Å，α=63.931(2) β=83.209(3) γ=85.057(3)°，T=296 K
- 期刊：Acta Crystallographica Section E **67** (2011) o2762，doi `10.1107/S1600536811038797`（Gomathi & Muthiah）
- 已发表 R1(gt) = 0.0656；COD 标记 has Fobs
- 为什么选它：阴离子–π 的教科书例子（BF₄⁻ 落在三嗪鎓环正上方），作者在摘要里给了
  **Cg1···F4ⁱ = 3.178 (3) Å、Cg1···F2ⁱ = 3.654 (3) Å**（对称码 (i) 1−x, 2−y, 1−z），
  同时给了环与其反演像的面对面堆积：**Cg···Cg 3.3361 (12) Å、面间距 3.333 Å、滑移角 2.46°**。
  一个结构同时校验 `anion_pi` 与 `pipi` 两张表；原有 14 个已知答案结构里没有一条阴离子–π 行。
- 已知答案的来源：论文摘要（检索引擎给出的摘要原文；IUCr 全文页对本机返回 403，未能直接打开）。
  本引擎的阴离子–π 行量的是**阴离子质心（B）到环质心**，所以测试在同一模型、同一算符下
  重新量出摘要里的两个 F···Cg 距离来核对是不是同一个接触。
- 沉积的 `_geom_hbond_*` 表（原文照抄，`test_deposited_hbond_table_is_reproduced` 自动核对）：

```
N1 H1 F1 . 0.86 1.90 2.758(2) 173 yes
N2 H2A F2 2_776 0.86 2.01 2.800(4) 152 yes
N2 H2B F4 1_556 0.86 2.02 2.877(4) 177 yes
N4 H4A F3 1_456 0.86 2.34 3.047(3) 139 yes
N4 H4B N5 2_567 0.86 2.18 3.038(3) 178 yes
```

## `helix_ptag_chain_cod4115425/ref.cif`（第三轮 R5-F 下载，2026-09-06）

- COD ID: **4115425** — <https://www.crystallography.net/cod/4115425.html>
- 化学式：`C53 H50 Ag2 Cl2 N4 O11 Pt2`
- 空间群 `P 61`（No. 169），a=b=14.8050(6) c=41.608(2) Å，γ=120°，Z=6，T=203(2) K
- 期刊：Journal of the American Chemical Society **123** (2001) 743，doi `10.1021/ja002906a`
  （Yamaguchi, Yamazaki & Ito，"A Helical Metal–Metal Bonded Chain via the Pt→Ag Dative Bond"）
- 已发表 R1(gt) = 0.0405
- 为什么选它：真实晶体里的螺旋链已知答案。论文标题即断言这是一条螺旋的 Pt→Ag 金属–金属键链；
  在 P6₁ 里，一条沿 c、每胞一个片段的链只能是 **6₁ 螺旋：右手，螺距 = c = 41.608 Å**，
  且群里没有非固有操作，不存在左手伴链（racemic = False）。
- 诚实说明：ACS 全文页对本机返回 403，摘要里是否给出螺距数字未能核对；
  测试断言的是**空间群 + 链方向的推论**（6₁、右手、螺距 = c），不是引用论文的数值。
  `tests/test_known_answers_topology.py::test_helix_known_answer_cod4115425`。
