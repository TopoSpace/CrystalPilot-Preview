# 拓扑与孔道几何：对文献已知答案的实弹校验（2026-09-04/05）

> **2026-09-05 复核更正：** 下文保留原实验记录；其中“对称相关即互穿”和“拓扑全部正确”的概括过强。Systre 验证的是各连通分量的网符号，并不独立证明这些分量如何互锁。本轮增加平行二维层反例；生产 API 已分离 `symmetry_related` 与互穿/互锁结论，多网的后两项为 `null`（未验证），分析缓存升级到 v6。网数、维度、连接数、网符号及孔径的数值对照仍有效。详见 `AUDIT-2026-09-05.md`。

对象：`crystalpilot/chem/topology.py`（独立网 / 互穿 / 节点–连接子简化网 /
Systre / 螺旋）与 `crystalpilot/chem/pores.py` + `crystalpilot/refine/scene.py`
（溶剂可及体积、LCD、PLD、通道维度）。

做法：拿五个**文献里已经有答案**的真实骨架 + 两个仓库自带 benchmark，
从 CIF 一路跑到拓扑与孔道数字，与文献/公开数据库逐项对照，
不一致的一律追到原因，属于代码缺陷的按**元素通用规则**修，
每条修复配一个**合成**回归测试。

---

## 一、结论摘要

- **拓扑全部正确。** 五个结构的网符号、节点连接数、互穿判定、维度
  **无一例外命中文献答案**：MOF-5 → `pcu`（Zn₄O 六连接）、HKUST-1 →
  `tbo`（Cu₂ 桨轮四连接 + btc 三连接）、ZIF-8 → `sod`（Zn 四连接）、
  UiO-66 → `fcu`（Zr₆ 十二连接）、互穿 MOF-5 → 两张 `pcu` 网、
  NU-1000 → `csq`（Zr₆ 八连接）。全部由 Systre 19.6.0 独立复核。
- **孔道数字全部落在容差内。** 与 CoRE MOF 2019（Zeo++ 高精度）逐项比：
  LCD 最大偏差 **0.28 Å**，PLD 最大偏差 **0.66 Å**（判据 ±0.6 / ±0.8 Å）。
- **发现并修掉 3 个真实缺陷 + 2 个测试硬编码假设**（见 §五）。其中
  `inscribed_sphere` 的抽样缺陷会让**更细的网格给出更差的 LCD**，
  是本轮最要紧的一条。
- **一个产品能力空洞（未修，如实报告）**：没有衍射数据的 CIF **根本进不了
  项目**，因此拿不到 `build_void_ccp4` 的空隙块；无数据通道
  `guests.host_void_map` 能给 LCD/体积/维度，但**不算 PLD**。见 §六。

---

## 二、口径（先说清楚再比数）

| 项 | 本平台 | 对照方 |
|---|---|---|
| 掩膜 | `cctbx.masks.around_atoms` + `flood_fill`，探针 1.2 Å、shrink 1.2 Å，网格步长 0.3 Å（默认） | Zeo++ 0.3 高精度 Voronoi 分解（解析，非网格） |
| vdW 半径 | `cctbx.eltbx.van_der_waals_radii`：C 1.775、H 1.20、O 1.45、N 1.50、Zn 1.39、Cu 1.40、Zr 1.42 | Zeo++ 默认（CCDC 系）；Sarkisov 基准强制 UFF（C 1.7155、H 1.2855） |
| LCD | 2×max R，R(x)=min_a(\|x−r_a\|−r_vdW(a))，在空隙格点上取**精确**最大 | Zeo++ `Di`（largest included sphere） |
| PLD | 2×sup{ρ：{R≥ρ} 仍沿某个晶格矢量渗流}，对**所有路径**二分，误差=网格步长 | Zeo++ `Df`（largest free sphere） |

**为什么允许 ±0.6 / ±0.8 Å**：①半径表不同，0.08 Å 的半径差就是 0.16 Å 的
直径差，窗口由两端原子夹住时再翻倍；②对照行是**同一种材料的另一次测定**
（不同晶胞、温度、无序处理），UiO-66 在 CoRE 自己的库里 LCD 就从
8.49 跨到 8.97 Å；③方法差：我们是网格二分，误差就是网格步长（默认约
0.29 Å），Zeo++ 是解析的。窄窗口只有几个体素宽，所以 **PLD 的尺子必须比
LCD 松**。

**为什么这五个结构不走 `RefineProject`**：`import_cif_model` 没有衍射数据
会直接拒绝（"no reflection data: the project has no crystal.hkl …"），
而 COD 对这五条记录都没有 .hkl。测试里用的是**同一套生产转换器**
（`_small_structure_to_xray` + `write_res`），只是绕过了数据闸门；
NU-1000 与 Zn3 有 sf.cif，走的是完整产品链路。

---

## 三、逐结构对照表

### 3.1 拓扑

| 结构 | 期望（文献） | 我们 | 判定 |
|---|---|---|---|
| MOF-5 / IRMOF-1（COD 1516287，Fm-3m, a=25.8247） | 1 张网, dim 3；`pcu`；Zn₄O 6-c ×8 | 1 张, dim 3；`pcu`；`{6: 8}` | ✅ |
| HKUST-1（COD 1546786，Fm-3m, a=26.2824） | 1 张网, dim 3；`tbo`；Cu₂ 桨轮 4-c ×24 + btc 3-c ×32 | 1 张, dim 3；`tbo`；`{4: 24, 3: 32}` | ✅ |
| ZIF-8（COD 7111973，I-43m, a=17.033） | 1 张网, dim 3；`sod`；Zn 4-c ×12 | 1 张, dim 3；`sod`；`{4: 12}` | ✅ |
| UiO-66（COD 4132633，Fm-3m, a=20.7123） | 1 张网, dim 3；`fcu`；Zr₆ 12-c ×4 | 1 张, dim 3；`fcu`；`{12: 4}` | ✅ |
| 互穿 MOF-5（COD 4324900，R-3） | **2 张** pcu 网互穿 | 2 张, dim [3,3]；`interpenetrated=True`；relation=`space_group_op`, op=`-x,-y,-z`；`{6: 12}`；Systre 两个分量都 `pcu` | ✅ |
| NU-1000（benchmark/public，P6/mmm） | `csq`；Zr₆ **8** 连接 + 四联吡蒽 4 连接 | `{8: 3, 4: 6}`；`csq` | ✅ |
| Zn3 2-D MOF（benchmark/public，P2₁/n） | 层状（dim 2） | 1 张网, **dim 2**；DMF/溶剂片段已按宿主规则移除 | ✅ |
| Mn3 对苯二甲酸 MOF（benchmark/public，C2/c） | 棒状 SBU 三维网 | dim 3；`{15: 2, 3: 4, 4: 1}`；Systre 算完但**该网不在 RCSR 档案**（"Structure is new for this run"） | ✅（如实报"无符号"） |

UiO-66 的 56 个连接子里有 **32 个记为 terminal**：就是 μ₃-OH 上那 32 个 H，
每个只触到一个 Zr₆ 簇，按规则不进网。这是**元素通用规则的正确表现**，
不是特例。

互穿 MOF-5 的宿主规则把 `F2 C6H14N2O2`（DEF）与 `F3 O`（水）判成客体移除，
剩下的骨架才切网，这一步如果不做，两张网会被客体桥接成一张。

### 3.2 孔道（默认 0.3 Å 网格；对照 = CoRE MOF 2019 ASR）

| 结构 | LCD 我们 | LCD 对照 | Δ | PLD 我们 | PLD 对照 | Δ | 维度 | 溶剂可及体积 | 堆积指数 |
|---|---|---|---|---|---|---|---|---|---|
| MOF-5 | **14.912** | 15.051（`EDUSIF_clean`） | 0.14 | **7.787** ±0.29 | 7.916 | 0.13 | 3-D，[100][010][001] | 13397 Å³ = 77.8% | 19.3% |
| HKUST-1 | **13.368** | 13.190（`FIQCEN_clean`） | 0.18 | **6.501** ±0.29 | 6.657 | 0.16 | 3-D | 12024 Å³ = 66.2% | 28.5% |
| ZIF-8 | **11.283** | 11.393（`VELVOY_clean`） | 0.11 | **2.799** ±0.28 | 3.409 | 0.61 | 3-D | 2394 Å³ = 48.5% | 39.9% |
| UiO-66 | **8.463** | 8.739（`RUBTAK04_clean`） | 0.28 | **3.208** ±0.29 | 3.867 | 0.66 | 3-D | 4594 Å³ = 51.7% | 41.4% |
| 互穿 MOF-5 | 7.283 | 无表可查 | — | 2.187 ±0.29 | 无表可查 | — | 3-D（另有 6 个孤立小腔，PLD 无定义） | 4313 Å³ = 33.5% | 51.7% |
| NU-1000（完整产品链路） | 28.83 | 30 Å（NLDFT PSD 介孔） | ~1 | 28.39 | — | — | 3-D | 17480 Å³ = 78.9% | 18.6% |

第二意见（不同半径口径，仅作旁证）：

- MOF-5：Nature 402 (1999) 276 逐字给出**距离**：大腔中心 72 个 C 在
  9.26 Å、48 个 H 在 9.47 Å；孔口 8 个 C 在 5.70 Å、8 个 H 在 5.10 Å；
  该文按自己的半径报 15.1 / 8.0 Å。把**同一批距离**代进我们的半径：
  LCD = 2×(9.26−1.775) = **14.97**、PLD = 2×min(5.70−1.775, 5.10−1.20) =
  **7.80**。我们实测 14.912 / 7.787 - **与解析预期差 0.06 / 0.01 Å**。
  这条是本轮最强的证据：孔道代码在同口径下几乎精确。
  （测试 `test_mof5_pore_geometry_reproduces_the_nature_1999_distances` 把
  这个换算钉住了。）
- Sarkisov 等（Chem. Mater. 32 (2020) 9849）随论文存放的 Zeo++/UFF 实跑
  文件：IRMOF-1 `15.03334 / 7.77347`、HKUST-1 `12.99975 / 6.33766`、
  ZIF-8 `11.39850 / 3.07308`；同结构 PoreBlazer v4.0 `7.80/15.03`、
  `6.38/12.86`、`2.86/11.42`。我们的 ZIF-8 PLD 2.799 正落在
  PoreBlazer 2.86 与 Zeo++ 3.07 之间。
- ZIF-8：PNAS 103 (2006) 10186 的 11.6 / 3.4 Å。3.4 Å 是**静态晶体学孔口**，
  同文即指出 ZIF-8 有 gate-opening 柔性。
- UiO-66：常引的"八面体腔 ~11 Å / 四面体腔 ~8 Å / 三角窗口 ~6 Å"是**标称
  值（未做 vdW 修正）**；减两个 vdW 半径后 ≈ 8.6 / 3.6 Å，与我们的
  8.463 / 3.208 及 Zeo++ 的 8.74 / 3.87 同一量级。

**网格步长的影响（已量化）**：把 PLD 在独立的全胞距离场上重算，
ZIF-8 步长 0.12 Å → 3.064，0.08 Å → 3.127（默认 0.3 Å 给 2.799）；
UiO-66 步长 0.10 Å → 3.501（默认给 3.208）。也就是说**默认网格把 PLD
系统性压低约 0.3 Å**，而报出的 `pld_error_A`（=网格步长）刚好覆盖这个量。
LCD 则在 0.288 / 0.144 Å 两档网格上**逐位相同**（修复后，见 §五.3）。

ZIF-8 的瓶颈由**碳**决定：把全部 H 去掉重算 PLD 一字不变（3.064），
说明六元环窗口是环碳夹出来的，不是 C–H。

---

## 四、Systre 运行日志摘录

Gavrog **Systre 19.6.0**（`vendor/gavrog/Systre-19.6.0.jar`，
sha256 `0d272e98…0d48d`，Apache-2.0，`vendor/` 已 gitignore）；
Java = OpenJDK 17.0.17 LTS。详见 `vendor/VENDOR-STATUS.md`。

MOF-5（我们的商图 → 标准 pcu）：

```
   Input structure described as 3-periodic.
   8 nodes and 24 edges in repeat unit as given.
   Ideal repeat unit smaller than given (3 vs 24 edges).
   1 kind of node.
   Coordination sequences:
      Node 1:    6 18 38 66 102 146 198 258 326 402
   TD10 = 1561
   Ideal space group is Pm-3m.
   Structure was identified with RCSR symbol:
       Name:		pcu
```

HKUST-1（两种节点，坐标序列 3… / 4… 正是 (3,4)-连接的 tbo）：

```
   56 nodes and 96 edges in repeat unit as given.
   Ideal repeat unit smaller than given (24 vs 96 edges).
   2 kinds of node.
   Coordination sequences:
      Node 25:    3 9 15 33 45 82 90 153 150 241
      Node 1:    4 8 20 30 60 68 120 126 200 180
   Ideal space group is Fm-3m.
   Structure was identified with RCSR symbol:
       Name:		tbo
```

互穿 MOF-5（**不连通**，Systre 分别处理两个分量，两个都是 pcu）：

```
   12 nodes and 36 edges in repeat unit as given.
   Structure is not connected.
   Processing components separately.
   ==========
   Processing component 1:
   ...  Structure was identified with RCSR symbol:  Name:  pcu
   ==========
   Processing component 2:
   ...  Structure was identified with RCSR symbol:  Name:  pcu
```

Mn3 对苯二甲酸 MOF（**修复前**：我们写出的 .cgd 有重边，Systre 直接
放弃整个文件）：

```
!!! ERROR (INTERNAL) - Unexpected java.lang.IllegalArgumentException: duplicate edge
!!!    at org.gavrog.joss.pgraphs.basic.PeriodicGraph.newEdge(PeriodicGraph.java:532)
```

修复后同一结构：

```
   7 nodes and 21 edges in repeat unit as given.
   4 kinds of node.
   Ideal space group is P-1.
   Structure is new for this run.
```

Zn3 2-D MOF（Systre 本身的限制，现在如实转述）：

```
!!! ERROR (STRUCTURE) - Structure has collisions between next-nearest
    neighbors. Systre does not currently support such structures..
```

---

## 五、发现的缺陷 → 通用修复 → 回归测试

### 5.1 `write_cgd` 写出重边，Systre 放弃**整个文件**

**现象**：Mn3 对苯二甲酸 MOF（COD 2204276）里两条晶体学独立的羧基以
**同一个晶格平移**桥连同一对 Mn 棒，简化后得到两条完全相同的
`1 2 -1 0 0`。Gavrog 的 `EDGES` 是一个**集合**，重复三元组触发
`IllegalArgumentException: duplicate edge`，并且它会放弃**整个 .cgd 文件**
，同一文件里其它结构一并丢失。而我们当时只报"输出里没有 RCSR 符号"，
既瞒住了 Systre 的理由，也瞒住了"问题出在我们写的文件上"。

**修复（通用）**：`chem/topology.py::write_cgd` 现在以集合去重
（`_canonical_edge` 已把 `2 1 -1 0 0` 规范成 `1 2 1 0 0`，所以反向写法
也算同一条）。重边不是错误，它是收缩网的真实性质，所以
`simplified_net` 新增 `n_parallel_edges` / `n_simple_edges_per_cell`
并在 `confidence` 里说明：**连接数直方图数的是连接子数，写给 Systre 的
是简单图，RCSR 符号命名的是合并后的简单图**。两个数不一致时明说，
不让它们无声打架。

**回归测试**（合成）：
`TestSystreBridgeRegressions::test_a_parallel_link_is_written_once`
（纯边表）与 `::test_parallel_links_are_counted_not_hidden`
（`_double_linked_pair()`：两个 Zn 被两条 O–C–O 桥以同一平移相连，
20 Å 立方 P1 胞，距离全部按 `chem/bonding.py` 的通用判据摆放，
不针对任何真实晶体）。

### 5.2 Systre 的报错/多分量结果被压平

**现象三连**：
1. `!!! ERROR (STRUCTURE) - Structure has collisions …` 被压成
   "已跑 Systre 但输出里没有 RCSR 符号"，Systre 的理由丢失；
2. "Structure is new for this run."（**算完了，只是这张网不在 RCSR 档案里**
   ，这是个答案，不是失败）同样被压成同一句话；
3. 不连通的网（**互穿就是这种**）Systre 会逐分量命名，而
   `parse_systre_symbol` 只取**第一个** `Name:`，两张 dia + 一张 pcu
   会被报成 "dia"，无声丢掉另外两个答案。

**修复（通用）**：新增 `parse_systre_symbols`（全部符号，按输出顺序）、
`parse_systre_error`（转述 Systre 自己的 `!!! ERROR (KIND) - msg`）、
`_read_systre`（统一裁决）。规则：所有分量符号一致 → 给该符号，
状态里说明"简化网不连通，N 个分量都是 X"；分量符号不同 → **不给单一符号**，
把清单摆出来；没有符号 → 分别报"Systre 报错：…"、"这个网不在 RCSR
档案里"、"输出里没有符号"。`run_systre` 的四个早退分支（无 jar / 无 java /
超时 / 起不来）统一走 `_systre_unavailable`，**键集完全一致**，调用方不必
判断某个键在不在。产品侧 `topology_from_res` 新增 `rcsr_symbols`
（`ANALYSIS_CACHE_V` 4 → 5）。

**回归测试**（合成，用罐装 Systre 文本，不需要 jar）：
`::test_systre_errors_are_reported_not_swallowed`、
`::test_a_net_systre_finished_but_could_not_name_is_not_a_failure`、
`::test_every_component_of_a_disconnected_net_is_named`、
`::test_the_gated_answers_all_have_the_same_shape`。

### 5.3 `inscribed_sphere` 的抽样是**各向异性**的：更细的网格给出更差的 LCD

**现象**：UiO-66 的八面体腔在 0.288 Å 掩膜网格上量到 **8.463 Å**，
在**更细的** 0.144 Å 网格上却只量到 **8.222 Å**。原因：空隙点来自
`np.argwhere`，是字典序（先 x 再 y 再 z）；超过 `MAX_SCAN_POINTS` 时代码做
`pts[::stride]`，这是**列表步长**，只在最快的那个轴上稀疏化，x、y 全采，
z 每 26 层才取一层，腔心正好落在两层之间。同一个 `stride` 又被
`scene.py` 当成各向同性的用（`step * stride**(1/3)`）报误差，那个模型也
从来不成立。这一条影响的是我们对外的**头号孔道数字 LCD**。

**修复（通用）**：改成"**格点稀疏 + 可证明的精化**"：
- `_thin_isotropic`：把点按规则分数格 nb×nb×nb 分箱，每个占用箱取一个代表，
  nb 用二分搜到刚好塞进预算，这是**空间均匀**的抽样，不是列表步长；
- R(x)=min_a(|x−r_a|−r_vdW(a)) 在笛卡尔空间是 **1-Lipschitz** 的，
  所以一个笛卡尔直径为 d 的箱最多藏住 d 的额外半径：把代表值落在
  `top − d` 以内的箱**全部保留**，真最大值必在其中（可证），再对这个更小的
  池重新分箱、重复，直到池能整体求值。于是结果是**交给它的那批点上的
  精确最大值**，误差回到调用方的网格步长本身；
- `scene.py` 的 `grid_step_A` 因此改回掩膜网格步长（不再乘 `stride**(1/3)`），
  并新增 `lcd_exact`（`VOIDS_CACHE_V` 4 → 5）。

**修复后**：UiO-66 在 0.288 / 0.144 Å 两档网格上都给 8.463，MOF-5 都给
14.912，HKUST-1 都给 13.368，ZIF-8 都给 11.283，且与**独立写的全胞
0.10 Å 距离场**逐位一致。

**回归测试**（合成，闭式解）：
`TestInscribedSphereRegressions::test_a_finer_scan_never_gives_a_smaller_sphere`
，12 Å 立方胞里放一个原子，最大内切球必在体心、半径
`12√3/2 − r_vdW(C)`；在 24³/48³/96³ 三档网格上（预算强制稀疏）半径必须
**单调不降**且都收敛到闭式解。另有 `::test_no_thinning_below_the_budget`。
`tests/test_pores.py::test_thinning_is_reported_and_still_finds_the_true_maximum`
（原 `test_subsampling_is_reported`）改成对**新契约**的断言：稀疏发生了，
但答案等于对全部点暴力求出的最大值。

### 5.4 两处测试硬编码了"本机没装 Systre"

`tests/test_analysis_product.py:130` 与 `tests/test_analyze_packing.py:111`
都断言 `rcsr_status.startswith("未算")`。`vendor/` 是 gitignore 的，
所以**只要有人装了 Gavrog 这两个测试就红**：本轮装上 jar 后立刻复现。
改成与 jar 无关的契约断言：状态必须是 `未算` / `已算` / `已跑` 三者之一，
且**有符号当且仅当状态是 `已算`**。

### 5.5 任务书给的合成对照 (½,½,½) 不成立（已更正为 ¼,¼,¼）

MOF-5 是 **F 心格**，(½,½,½) ≡ (0,0,½) mod F，正好把结构映回它自己，
实测两份拷贝的最近原子距离 **0.000 Å**。拿它做"MOF-5 + 自身平移拷贝"
得到的是"同一批原子写了两遍"，连通后仍是**一张**网，测不出互穿。
正确的位移是 **(¼,¼,¼)**（pcu 立方体的半条体对角线，也正是真实互穿
MOF-5 的相对位置）：最近距离 **3.67 Å**，远在任何成键判据之上，
两张网真的互不接触地穿过。合成对照因此断言
`n_nets=2`、`dims=[3,3]`、`interpenetrated=True`、
`relation="translation"`、`shift=[0.25,0.25,0.25]`、`{6: 16}`。

---

## 六、没能验证 / 无法验证的

1. **无衍射数据的 CIF 拿不到空隙块（产品空洞，本轮未修）**。
   `import_cif_model` 没有 hkl 直接失败 → 没有节点 → `build_void_ccp4`
   （它 `_build_session` 要 `fo_sq`）根本到不了。无数据通道
   `guests.host_void_map` 能给体积/维度/LCD，但**不算 PLD**；本轮测试是
   自己再调一次 `pores.pore_limiting_diameter`。要让"只有 CIF 的结构也能
   看孔道"，需要给 `host_void_map` 补 PLD、或给产品加一条无数据空隙路径
   ，这是**功能新增**，不是缺陷修复，留给决策。
2. **HKUST-1 的 PLD "6.9 Å" 查无出处**。能查到的实测值是 CoRE MOF 2019
   `FIQCEN_clean` **6.657**、PoreBlazer v4.0 **6.38**、Zeo++/UFF **6.35**
   （半径表不同）。本报告按 6.657 对照。
3. **Chui 1999（HKUST-1）与 Cavka 2008（UiO-66）的正文数字未能一手核对**
   ，两篇都是全封闭获取，无任何 OA 副本。Chui 的摘要只说
   "channels with a pore size of 1 nanometer"，且**未说明是否做过 vdW 修正**；
   Cavka 的摘要与免费 SI 里**根本没有腔/窗口尺寸**，流传的
   "11 / 8 / 6 Å" 是二手转述。因此这两条只当旁证，判据用
   CoRE MOF 2019 的实测行。
4. **NU-1000 的 "31 Å"** 查不到出处：一手文献（JACS 135 (2013) 10294）
   写的是 **30 Å**，且那是 NLDFT 孔径分布的峰位（等效孔宽），不是晶体学
   距离，所以 NU-1000 的孔径只作量级核对，不进 ±0.6 Å 判据。
5. **互穿的"晶体学独立网"这一类没有测例**。本模块的定义（`DEF_NETS`）
   只把**对称相关**的拷贝叫互穿；两张组成相同但没有任何操作互映的网会报
   `independent`。这是模块**写明的**取舍，但与 Batten–Robson / TOPOS 的
   分类不一致（后者把这种也算互穿，属 Class III）。本轮选的互穿 MOF-5
   两网恰好由 R-3 的反演中心相关，**没有触到这个边界**。真要覆盖它，
   需要一个几何缠绕判据（环–穿越检测），模块自己也声明未做。
6. **Sarkisov 2020 的 Table 2 排版页**没打开（ChemRxiv/曼大仓库都 403），
   用的是作者随论文存放的 Zeo++/PoreBlazer **实跑输入输出文件**
   （`PB4.0_vs_Zeo++_vs_RASPA.zip`），证据力只强不弱。
7. **螺旋**：这七个结构里没有一维螺旋链，`helices()` 一律返回空列表，
   本轮**没有对螺旋做任何新的实弹校验**（合成校验在
   `tests/test_topology.py` 里）。

---

## 七、复现命令

```bash
# 1. Systre（vendor/ 已 gitignore，二进制不入库）
mkdir -p vendor/gavrog
curl -sL -o vendor/gavrog/Systre-19.6.0.jar \
  https://github.com/odf/gavrog/releases/download/Systre-19.6.0/Systre-19.6.0.jar
sha256sum vendor/gavrog/Systre-19.6.0.jar   # 0d272e98a1a21669bc67a809b95c014ba2a2fb39a6fd2147039201216ab0d48d
java -version                                # OpenJDK 17.0.17 LTS

# 2. 已知答案结构（每个目录的 SOURCES.md 里有同样的命令与文献值）
for id in 1516287 1546786 7111973 4132633 4324900; do
  curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/$id.cif
done
# -> benchmark/known_answers/{MOF-5_IRMOF-1,HKUST-1,ZIF-8,UiO-66,interpenetrated_MOF-5}/ref.cif

# 3. 测试（Windows 控制台是 GBK，必须 -X utf8）
mkdir -p workdir/pytest-tmp
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/test_known_answers_topology.py \
  --basetemp=workdir/pytest-tmp/known -p no:cacheprovider -q
# 37 passed, 约 2 分 10 秒

H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/test_topology.py tests/test_pores.py tests/test_scene.py \
  tests/test_analysis_product.py tests/test_analyze_packing.py \
  --basetemp=workdir/pytest-tmp/reg -p no:cacheprovider -q
```

注：`tests/test_scene.py` / `tests/test_analysis_product.py` 的
`workbench/mvp-sjtu9` 夹具需要 `crystal.hkl`，而 `.gitignore` 有
`workbench/**/*.hkl` - **新建的 worktree 里这个文件不存在，两个测试会以
`hkl_path=None` 报 TypeError**。从主库拷一次即可
（`cp H:/CrystalPilot/workbench/mvp-sjtu9/crystal.hkl workbench/mvp-sjtu9/`），
这与本轮改动无关。
