# 相互作用表的"已知答案"验证（2026-09-05）

对象：`crystalpilot/chem/interactions.py`（`find_interactions`）及其产品包装
`crystalpilot/refine/analysis.py::interactions_from_res`。
目的：确认系统展示的氢键 / π–π / C–H···π / C–H···X / 卤键表里，**伙伴原子对不对、
对称算符对不对、距离角度对不对、pass/fail 判得对不对**。

用的是两套与本仓库无关的独立答案：

1. **作者沉积的 `_geom_hbond_*` 表**（14 个已发表结构的 CIF 里作者自己列的氢键表，
   带对称码、D–H、H···A、D···A、角度）；
2. **PLATON**（`vendor/shelx/platon.exe`，V-60124，(C) A.L.Spek）在**同一个模型**上
   无头运行 `CALC INTRA` + `CALC INTER`（+ `CALC SOLV`）后的
   "Analysis of Potential Hydrogen Bonds"、"Analysis of Short Ring-Interactions with
   Cg-Cg Distances"、"Analysis of X-H...Cg(Pi-Ring) Interactions"、
   "Analysis of Short Intra- and Inter-molecular Contacts"、
   "Search for and Analysis of Solvent Accessible Voids" 五张表。

---

## 0. 结论（数字）

| 对照源 | 比对行数 | 完全一致 | 不一致 | 备注 |
|---|---|---|---|---|
| 沉积 `_geom_hbond_*`（14 个结构） | **78** | **76** | 0（另有 2 条为判据边界，见 §4-B） | 算符 76/76 精确一致 |
| PLATON 氢键表（14 个结构） | **76** | **76** | 0 | 含 C–H···O/N/F |
| PLATON Cg···Cg（π–π） | **5**（2026-09-06 起 **18**，见 §9） | **5** | 0 | 另 28 条按引擎自述判据豁免，见 §4；§D 的 20 条中 12 条自 R3-R5 起进入比对 |
| PLATON X–H···Cg（C–H···π） | **9** | **9** | 0 | 另 8 条豁免（4 跨 PART、4 穿对称环） |
| PLATON vdW 接触表（卤键 X···Y） | **14** | **14** | 0 | 含 4 条真正的 C–I···N |
| PLATON `CALC SOLV` 溶剂可及体积 | 1 个结构 | 9202.8 vs 9082.7 Å³（差 **1.3 %**） | — | 判据要求 ±15 %，见 §6 |

76 条已复现沉积行的最大偏差：**D···A ≤ 0.0015 Å，H···A ≤ 0.0094 Å，角度 ≤ 0.72°，
对称算符不符 0 条**。

发现并处理的问题：**1 个引擎缺陷（"沉默的环缺口"，已改为量化披露 + 合成晶体回归测试）**；
另有 5 类"不是缺陷的差异"，逐条量化写在 §4。

---

## 1. 方法

### 1.1 模型来源（保证"苹果对苹果"）

`tests/test_known_answers_interactions.py::known_model`：
CIF 里若嵌有 `_shelx_res_file` 就用它（`io/shelx_model.load_res_model`，能带出 SHELX
PART 号），否则走产品自己的导入路径（gemmi → `tools_ingest._small_structure_to_xray`），
无序组由 `_atom_site_disorder_group` 提供。引擎、沉积表、PLATON 三方拿到的是同一批坐标。

14 个结构中 7 个走嵌入 res、7 个走 CIF 原子环。

### 1.2 判据

- 引擎：`criteria="platon"`（= Steiner：H···A ≤ r_vdW(H)+r_vdW(A)，D–H···A ≥ 110°）
  为主；另跑 `criteria="olex2"`（D···A ≤ 2.9 Å，角 ≥ 150°）核对窄判据不丢行。
- PLATON 自述判据（.lis 原文）：
  - 氢键 `d(D...A) < R(D)+R(A)+0.50, d(H...A) < R(H)+R(A)-0.12 Ang., D-H...A > 100.0 Deg`
  - 环–环 `Cg-Cg Distances < 6.0 Ang., Alpha < 20.000 Deg. and Beta < 60.0 Deg.`
  - X–H···Cg `H..Cg < 3.0 Ang. - Gamma < 40.0 Deg`
  - 接触 `d(I-J) < R(I) + R(J) + Tolr, With Tolr = 0.2 Ang. (X - I...J) > 100. Deg.`
- 容差：D···A 0.01 Å，H···A 0.02 Å，角 1°（沉积表与 PLATON 都只印到 2 位小数/整度，
  1° 就是它们自己的取整宽度）；π–π 距离 0.01 Å、角 0.5°。

### 1.3 怎样在 Windows 上无头驱动 PLATON（这一步花了最多时间，记录下来）

失败的尝试（都试过，都不行）：

- `platon -h` / `platon -c file.cif`：`-h`/`-c` 不是开关，被当成文件名（`platon.out` 写
  `E: Check Data Type (cif,ins,res,spf,pdb,fcf) of the Input`）。
- `platon -o model.cif`、`platon model.cif < cmd.txt`、`platon -o model_sx.ins < cmd.txt`：
  进程挂起，所有输出文件 0 字节。原因是 PLATON 读完输入文件后弹 `>>` 提示符等键盘输入，
  而 Windows 版（Salford/ClearWin 运行时）不接管重定向的 stdin。
- `platon -u model.cif`（仓库里 `tools_deliver.py` 用的 checkCIF 模式）：能跑完并写
  `model.chk`/`model.ckf`，但**不写 `.lis`**，`.ckf` 里只有 "Section 12: ASYM Reflection
  Averaging Listing"，没有几何相互作用表。

**可行做法**（`tests/test_known_answers_interactions.py::platon_spf` + `platon_calc_all`）：
把模型写成 PLATON 自己的 `.spf`，并把指令直接放在数据后面、以 `END` 收尾，再
`platon m.spf`。PLATON 从文件里读指令，读到 `END` 就正常结束，永远走不到 `>>` 提示符：

```
TITL <name>
CELL 0.71073 a b c alpha beta gamma
SPGR <H-M 符号，去空格>
ATOM <label> x y z occ        (每原子一行；ATOM 的第 5 列是 pop/占有率)
NOMOVE
CALC INTRA
CALC INTER
END
```

- `NOMOVE` 必须写：不写的话 PLATON 会把分子搬到标准位置，它的 ARU 码就不再和我们的算符
  同框（实测 MeIm 的 Cg2 会整体差一个 c 平移）。写了以后，PLATON 的 ARU 与我们的 `op`
  **逐条精确相同**。
- `CALC INTRA` 出环/平面分析（两张 π 表挂在它下面），`CALC INTER` 出接触表和氢键表；
  `CALC ALL` 也行但慢很多（还会跑 ADDSYM/VOID）。小结构 5 s 左右。
- ARU 码 `sklm.nn` 的解码：`s` = PLATON 自己编号的对称操作（.lis 的
  "Space Group Symmetry" 段里印出），`klm` = 平移 +5，`nn` = residue 号；
  `platon_symops()` / `decode_aru()` 就干这个。
- PLATON 跑完常常不退出（仓库里早有记录），所以按 `.lis` 大小稳定来判完成并主动 kill。

### 1.4 复现命令

```bash
# 全量对照报告（含 PLATON，约 6 分钟）
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 tests/test_known_answers_interactions.py
# 只跑不依赖 PLATON 的断言
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/test_known_answers_interactions.py -q -m "not slow" \
  --basetemp=workdir/pytest-tmp/ka -p no:cacheprovider
# PLATON 交叉检验
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/test_known_answers_interactions.py -q -m "slow" \
  --basetemp=workdir/pytest-tmp/ka -p no:cacheprovider
```

`benchmark/data_ext2/*/ref.cif`、`benchmark/public/*/ref_cif.cif`、
`workbench/mvp-sjtu9/crystal.hkl` 都是 gitignore 的工作数据；缺文件时相应测试自动 skip。
新下载的卤键结构在 `benchmark/known_answers/xb_tfib_bipy_cod2201150/`，出处见同目录
`SOURCES.md`（COD 2201150，Acta Cryst. E 2002，doi 10.1107/S1600536802007201）。

---

## 2. 逐结构：沉积表 vs 引擎

"落表"列是沉积行落在我们哪张表里：C–H···O 落 `chx`、C–H···Cg 落 `chpi`，这是本引擎按
**给体元素**分类的既定设计（模块自述："a polar carrier makes it a hydrogen bond and it is
reported as one"），不是分歧，几何仍必须对上。

| 结构 | 模型来源 | 原子 | 空间群 | 沉积行 | 复现 | 落 hbond | 落 chx | 落 chpi | 未复现 |
|---|---|---|---|---|---|---|---|---|---|
| coord_cuox_cod2241944 | 嵌入 res | 12 | P2₁/c | 6 | 6 | 6 | 0 | 0 | 0 |
| coorddis_cuspar_cod2241447 | CIF 原子环 | 68 | P2₁/c | 10 | 10 | 7 | 3 | 0 | 0 |
| org_hsl_cod2241460 | 嵌入 res | 24 | P2₁2₁2₁ | 1 | 1 | 1 | 0 | 0 | 0 |
| orgdis_dbu_cod2241572 | CIF 原子环 | 54 | P2₁/n | 7 | 7 | 2 | 5 | 0 | 0 |
| twin_iodouracil_cod2020129 | 嵌入 res | 12 | P2₁ | 2 | 2 | 2 | 0 | 0 | 0 |
| twin_rz5267_iucr | 嵌入 res | 32 | C2/c | 3 | 3 | 1 | 2 | 0 | 0 |
| twindis_hb8035_iucr | 嵌入 res | 130 | P2₁/c | 10 | 10 | 3 | 4 | **3** | 0 |
| twintrap_nm_cod2229074 | CIF 原子环 | 44 | P-1 | 4 | 4 | 1 | 3 | 0 | 0 |
| Ca_imidazolate | CIF 原子环 | 26 | P2₁/c | 4 | 4 | 4 | 0 | 0 | 0 |
| Cd_complex_P1 | CIF 原子环 | 105 | P1 | 5 | 5 | 5 | 0 | 0 | 0 |
| Cu3_terephthalate_CP | 嵌入 res | 41 | P-1 | 8 | 8 | 8 | 0 | 0 | 0 |
| MeIm_H_terephthalate | CIF 原子环 | 30 | P-1 | 5 | 5 | 3 | 2 | 0 | 0 |
| Zn2_dhtp_complex | CIF 原子环 | 50 | P-1 | 8 | 8 | 8 | 0 | 0 | 0 |
| xb_tfib_bipy_cod2201150 | CIF 原子环 | 64 | I2/a | 5 | 3 | 0 | 3 | 0 | **2**（§4-B） |
| **合计** | | | | **78** | **76** | 51 | 22 | 3 | 2 |

沉积表里三条 C–H···Cg（twindis_hb8035，作者用 `Cg1`/`Cg2` 当受体标签）也逐条对上了：

| 沉积行 | 沉积 H···Cg / 角 | 我们 `chpi` | 算符 |
|---|---|---|---|
| C31–H31···Cg1 (3_655) | 2.72 / 145 | 2.7152 / 144.711 | −x+1,−y,−z ✓ |
| C25–H25···Cg1 (2_644) | 2.70 / 146 | 2.7023 / 146.351 | −x+1,y−1/2,−z−1/2 ✓ |
| C23–H23···Cg2 (3_665) | 2.75 / 154 | 2.7479 / 153.606 | −x+1,−y+1,−z ✓ |

### 我们多出来的行（"extra"）怎么分类

沉积表是作者挑过的，我们的表是判据下的全集，所以必然更长。148 条 extra 行里：

- **47 条**同时满足 `passes=True` 且 `intra=False`，这才是使用者在 `analyze_packing`
  里真正看到的（该工具只放行 `passes and not intra`）；按类型：`chx` 为主，
  少量 `hbond`（作者未列的分叉氢键）与 `chpi`。
- 其余 101 条是 `passes=False`（角度不过）或 `intra=True`（分子内），按模块设计"先给测量、
  再给判词"而保留。其中绝大多数是**分子内 1-4 接触**：本引擎只排除共价 1-2/1-3，PLATON
  额外排除"相隔不足 4 根键"的分子内对，所以这些行 PLATON 不列（见 §4-F）。

逐结构 extra 数（extra / 其中 passing+intermolecular）：
cuox 0/0，cuspar 23/2，hsl 9/5，dbu 20/5，iodouracil 1/0，rz5267 10/1，hb8035 26/9，
nm 15/0，Ca_imid 2/2，Cd_P1 18/16，Cu3 6/1，MeIm 10/3，Zn2 7/2，tfib_bipy 1/1。

### 窄判据（olex2）不丢行

`test_olex2_preset_keeps_every_deposited_row_inside_its_own_limits`：所有极性给体、
D···A ≤ 2.9 Å 的沉积行在 `criteria="olex2"` 下也全部在 `unique.hbond` 里（14/14 结构通过）。

---

## 3. PLATON 交叉检验

### 3.1 氢键（76 行，0 处不符）

PLATON 的窗口比我们窄（`R(H)+R(A)−0.12` vs 我们的 `R(H)+R(A)`，角 100° vs 110°/120°），
所以**它列的每一行我们都必须有**。14 个结构、76 行，逐行对上 D/H/A 标签、算符、
H···A（≤0.02 Å）与角度（≤1°），**0 处不符**。

### 3.2 π–π（5 行比对，0 处不符）

比对到的行（PLATON 表在我们 4.0 Å / 30° 窗口内的部分）例：

| 结构 | 环对 | PLATON Cg–Cg / α / CgI⊥ / CgJ⊥ / slip | 我们 | 算符 |
|---|---|---|---|---|
| MeIm_H_terephthalate | 苯环自身 | 3.7060 / 0 / 3.4521 / 3.4521 / 1.348 | 3.706 / 0.0 / 3.4521 / 3.4521 / 1.3482 | −x,−y+1,−z+1 ✓ |
| MeIm_H_terephthalate | 咪唑鎓自身 | 3.5690 / 0 / 3.4765 / 3.4765 / 0.808 | 3.569 / 0.0 / 3.4765 / 3.4765 / 0.8075 | −x+1,−y,−z ✓ |

另 2 条来自 twintrap_nm、1 条来自 Ca_imidazolate，同样精确。
`alpha` 用的是**法向夹角**，与 PLATON 的 Alpha 定义一致；`slip_ab/slip_ba` 与 PLATON 的
Slippage 一致；`d_perp_ab/d_perp_ba` 与 CgI_Perp/CgJ_Perp 一致。

### 3.3 C–H···π（9 行比对，0 处不符）

除距离/角度外还核对了 PLATON 的 **Gamma**（Cg–H 向量与环法向的夹角）：我们不直接给
gamma，但 `acos(d_perp / d_HCg)` 必须等于它（±0.5°），9 行全过。例：
MeIm C11–H11···Cg1，PLATON 2.60 Å / γ 3.44° / 149°；我们 2.5984 / γ 3.42° / 148.95°。

### 3.4 卤键（14 条接触比对，0 处不符）

CIF 没有卤键的 `_geom_*` 循环，所以用 PLATON 的 vdW 接触表当答案（它给 I···Y 距离和
C–I···Y 角）。为此专门下载了 COD 2201150（4,4′-联吡啶·1,4-二碘四氟苯共晶），原有 13 个
基准里一条通过判据的卤键都没有。四条真实的 C–I···N σ-hole 键：

| 行 | PLATON d / 角 | 我们 d_XA / 角 / passes | 算符（PLATON vs 我们） |
|---|---|---|---|
| C1A–I1A···N4C | 2.9277 / 172.07 | 2.9276 / 172.074 / True | x,y,z = x,y,z ✓ |
| C1B–I1B···N4D | 2.9095 / 172.45 | 2.9093 / 172.452 / True | x,y,z ✓ |
| C2A–I2A···N10C | 2.9581 / 175.36 | 2.9581 / 175.364 / True | x,−y−1/2,z−1/2 ✓ |
| C2B–I2B···N10D | 2.9639 / 176.16 | 2.9640 / 176.159 / True | x−1/2,−y+1,z ✓ |

同时核对了 9 条**不通过**的行（I···F、I···I 的分子内/侧向接触，角 48–87°），`passes` 与
IUPAC 155° 判据逐条自洽；5-碘尿嘧啶里唯一的 I···O（3.2711 Å、C–I···O 46.9°、分子内）
我们也标为 `passes=False`，该多晶型确实没有分子间卤键，PLATON 的接触表印证了这一点。

---

## 4. 所有差异及其原因（逐类量化）

### A. 类型归属（不是分歧）：25 条

沉积 `_geom_hbond` 表里的 C–H···O / C–H···F / C–H···Cg 行，本引擎按给体元素归到 `chx`
（22 条）与 `chpi`（3 条）。几何全部对上。测试 `test_deposited_rows_land_in_the_expected_table`
把这条规则钉死：给体元素 ∈ `HBOND_ELEMS` → `hbond`，碳给体 + 原子受体 → `chx`，
碳给体 + 环受体 → `chpi`，**由元素决定，与结构无关**。

### B. 判据边界：2 条（唯一"未复现"的沉积行）

COD 2201150：

| 行 | 沉积 H···F | 我们重算 H···F | `r_vdW(H)+r_vdW(F)` | 超出 |
|---|---|---|---|---|
| C5C–H5C···F3A (5_555) | 2.68(3) | 2.6758 | 2.67 | **+0.006 Å** |
| C2D–H2D···F1A (7_554) | 2.69(4) | 2.6848 | 2.67 | **+0.015 Å** |

几何本身与沉积表一致（D···A、角度都在容差内），差的只是截断：cctbx 的 F 半径 1.47 Å
（Bondi），我们的 C–H···X 判据是 `H···A ≤ r_vdW(H)+r_vdW(A)`（模块自述），这两条恰好在
外侧 6–15 mÅ。**没有为此改判据**：改成 +0.1 Å 之类是没有出处的调参。改成
`KNOWN_GAPS` 里的两条带理由记录，并由
`test_documented_gaps_are_boundary_cases_of_the_stated_criterion` 每次重新量：
① 这行确实不在表里；② 从沉积模型重算的几何仍与沉积表一致；③ 超出量 < 0.02 Å。
一旦引擎开始报这行、或偏差变大，测试立刻失败。

### C. π–π 只算芳香环：8 条 PLATON 行被豁免

PLATON 的环–环分析把所有平面环（含金属螯合环）都算进去；本引擎的 `criteria.pipi.rings`
明写 `"aromatic only"`。被豁免的 8 条全部涉及金属螯合环：
coord_cuox 的 Cu–草酸五元环（4 条，Cg–Cg 3.189 Å）、coorddis_cuspar 的 Cu 螯合环（4 条，
3.5311 Å / α 5°）。测试里这类行必须被引擎自己的判据解释（分类为 `ours_not_aromatic`）
才放行，否则算失败。

### D. 穿对称元素闭合的环：20 条 PLATON 行（**唯一的引擎缺陷，已处理**）

坐在反演中心上的苯环，在不对称单元里只有 3 个碳，环要靠 `-x,-y,-z` 才闭合。
`peak_chemistry.find_rings` 按构造拒绝这种环（"a lattice loop is not a ring" 的对称合成检查），
于是这些环连同它们的 π–π / C–H···π 行全部消失。**这不是理论风险**：

- `Zn2_dhtp_complex`：PLATON 找到 9 个环，其中 Cg5 = C14,C15,C16(+反演像)、
  Cg9 = C18,C19,C20(+反演像) 就是这种环。我们的 `unique.pipi` **是空的**，而 PLATON
  在 3.48–3.85 Å、α 1–11° 处有 16 条涉及这两个环的堆积行（另 4 条涉及 8 元并环，
  `find_rings` 只搜 5/6 元环）。也就是说这个 MOF 的 π–π 表整张缺失。
- `coorddis_cuspar_cod2241447`：Cg8 = C20,C21,C22(+反演像)，导致 4 条 C–H···π 缺失。
- `Cu3_terephthalate_CP`：2 个穿反演的 Cu–O 六元环（非芳香，对 π–π 无影响）。

原来的披露只是一句泛泛的"这种环检测不到"，读者无法判断**手上这张表**是否完整。
改动见 §5。

### E. 跨 PART 排除：4 条 PLATON 行（我们对，PLATON 无从知道）

`twindis_hb8035_iucr` 有两套无序构象（带撇号标签）。PLATON 报的 8 条 X–H···Cg 里有 4 条把
PART 1 的 C–H 指向 PART 2 的环（C25→Cg7、C31→Cg7、C25′→Cg3、C29′→Cg4）。本引擎按 D19
规则（`abs(part)` 不同的非零 PART 不配对）正确排除；PLATON 拿到的 `.spf` 只有占有率、
没有 PART 连结信息，无从区分构象。测试里这类行由**模型自己的 parts** 判定后豁免。

### F. 分子内 1-4 接触：我们列、PLATON 不列

PLATON 的接触表原文写着 `Short "INTRA" Distances between two Atoms that are Separated by
less than 4 Bonds are NOT Listed`；本引擎只排除共价 1-2/1-3。于是我们的 `chx` 表里会多出
一批 `intra=True`、角度 96–100° 的行（例：MeIm 的 C5–H5···O4，2.7458 Å / 99.2°）。
它们 `passes=False` 且 `intra=True`，`analyze_packing` 只放行 `passes and not intra`，
所以不会出现在用户看到的表里。这是"先测量后判词"的既定设计，不改。

---

## 5. 引擎改动（1 处）与回归测试

**改动**：`crystalpilot/chem/interactions.py`
新增 `_heavy_graph()` / `_op_order()` / `_rings_through_symmetry()`，
`_ring_defs()` 现在返回 `(rings, note, rings_through_symmetry)`，
`criteria.pipi` 与 `criteria.chpi` 新增字段 **`rings_closing_through_symmetry`**，
`ring_note` 从"这种环可能存在"改成对**这个结构**的判断：

- 有：`THIS STRUCTURE HAS 2 of them (C14,C15,C16 x -x+2,-y,-z; C18,C19,C20 x -x+1,-y,-z+1):
  every pi-pi and C-H...pi row that would involve one of those rings is MISSING from the
  tables below.`
- 没有：`No such ring exists in this structure (the asymmetric-unit bond graph was searched
  for cycles closing on a non-identity operator of finite order).`

**规则是通用的**：在不对称单元的重原子键图上走环，接受 `find_rings` 丢弃的那种闭合，
合成算符**非恒等且阶 n 有限**，且 `路径长度 × n` 落在 `find_rings` 搜索的环尺寸 (5,6) 内。
纯拓扑 + 空间群算符，不看元素、不看标签。带螺旋/滑移分量的算符没有有限阶，因此纯平移
闭合的一维链**不会**被误报成"缺失的环"（这正是 `find_rings` 原本要挡的东西）。

**没有做的事**：没有真去补出这些环。模块文档明确写过这是"on purpose"的不实现项
（"rather than inventing a second ring finder"），在一次验证任务里推翻这个设计决定不合适。
现在的效果是：表还是缺，但**缺什么、缺几个、缺在哪**写在判据里，`analyze_packing` /
分析产品会原样带出去。补齐这些环需要扩展 `peak_chemistry.find_rings` 的返回契约
（环要能带重复的 ASU 下标 + 每原子算符），影响 `scene`/`tools_analysis`/峰解释多处，
建议单独立项。

`crystalpilot/refine/tools_analysis.py` 只改了一处解包（`_ring_defs` 现在返回三元组）。

**回归测试**（合成晶体，`tests/test_interactions.py::TestRingsThatCloseThroughSymmetry`）：

1. `test_benzene_on_an_inversion_centre_is_named`：P-1、半个正六边形放在原点，
   断言 `rings_closing_through_symmetry` 恰好 1 条、size 6、op_order 2、op `-x,-y,-z`、
   成员 {C1,C2,C3}；并断言 `rings` 仍为空、`unique.pipi` 仍为 0（这是披露，不是新环搜索）。
2. `test_a_whole_ring_in_the_cell_reports_none`：整环写全的对照，断言"本结构没有这种环"。
3. `test_a_lattice_loop_is_not_counted_as_a_ring`：一维链（靠纯平移闭合）不得被计入。

---

## 6. 顺带验证：溶剂可及体积（`CALC SOLV` vs `build_void_ccp4`）

同一个模型（`workbench/mvp-sjtu9` 节点 n0013，I4₁/amd:2，V = 14449.3 Å³）：

| | 探针 | 网格 | 溶剂可及体积 |
|---|---|---|---|
| PLATON `CALC SOLV` | 1.20 Å | 0.20 Å | **9202.8 Å³**（64 % of cell） |
| 本仓库 `refine/scene.build_void_ccp4` | 1.20 Å | 0.541 Å | **9082.7 Å³**（62.9 %） |

相对差 **1.3 %**，远在 ±15 % 判据内（两者网格步长差 2.7 倍，符号也对：粗网格略偏小）。
注意 PLATON 这一步在这个大晶胞上跑了十几分钟且跑完不退出，所以它**没有**写进自动化测试，
只在本报告里留下数字和复现方式。

---

## 7. 没能验证 / 仍不确定的部分

1. **`anion_pi`**：没有任何独立答案。CIF 没有这种循环，PLATON 的 `Y-X...Cg` 表是"非氢
   给体指向环"，与我们"阴离子片段质心 → 环质心"的定义不是一回事。14 个结构里只有
   `Cd_complex_P1` 出了 1 条（`passes=False`）。**这一类目前完全未经外部核对。**
2. **esd**：引擎按设计不给标准偏差（只有 SHELXL 有），沉积表的括号值因此没有对照对象；
   本次只比数值，不比 esd。
3. **π–π 的比对样本仍偏薄**：真正落进我们 4.0 Å / 30° 窗口的 PLATON 行只有 5 条
   （多数结构的最近环对在 4.3–6.0 Å）。新下载的卤键共晶最近环对 4.3355 Å，也在窗口外。
   要把 π–π 压满，需要再找 2–3 个强堆积芳香结构（如芘/苝类）。
4. **`halogen` 的 Br/Cl 分支**：只验证了 I（4 条 C–I···N + 9 条不通过行），Br/Cl 的 σ-hole
   行为未取到已知答案。
5. **PLATON 的无序处理**：`.spf` 只能传占有率，传不了 PART 连结，所以在
   `coorddis_cuspar` / `orgdis_dbu` / `twindis_hb8035` / `twintrap_nm` 四个无序结构上，
   PLATON 与我们的"哪些对该配"必然有系统差（§4-E）。这是对照方法本身的上限，
   不是任何一方的错。
6. **`connectivity.short_contacts` 不在本次范围**：那是"比共价半径还短"的报警清单
   （validation 用），与本文说的 vdW 接触表不是一个概念；本次没有对它做已知答案验证。
7. **`coorddis_cuspar` 的 `chpi` 只有 1 条而 PLATON 有 4 条**：这 4 条全部指向穿反演闭合的
   Cg8（§4-D），是同一个缺口的另一处表现，不是新问题。

---

## 8. 涉及的文件

- 新增 `tests/test_known_answers_interactions.py`（对照 + PLATON 驱动 + 解析 + 报告模式）
- 新增 `benchmark/known_answers/SOURCES.md`、`benchmark/known_answers/xb_tfib_bipy_cod2201150/ref.cif`
- 改 `crystalpilot/chem/interactions.py`（§5）、`crystalpilot/refine/tools_analysis.py`（解包）
- 改 `tests/test_interactions.py`（新增 `TestRingsThatCloseThroughSymmetry` 三个合成晶体测试）
- 改 `pyproject.toml`（注册 `slow` marker）

---

## 9. 2026-09-06 更新（第三轮 R5-A / R5-F）：§D 的环已经建出来了

§5 里"没有真去补出这些环"的决定在第三轮 R5-A 推翻：`chem/interactions.py` 的
`_rings_through_symmetry` 现在记录闭合路径、每步算符与闭合算符，`_ring_defs` 用
闭合算符的幂把整环铺出来（阶 n 有限、路径长 × n 落在 5/6 元），几何走同一个
`_ring_geometry`，环行带 `through_symmetry {op, order, asu_atoms}`，普查条目带
`built` / `aromatic`。`ring_note` 改为"本结构有 N 个这种环，已建出并参与每一条
π–π / C–H···π"。规则仍是纯拓扑 + 空间群算符，不看元素、不看标签。

**效果（同一套 PLATON 交叉比对）**：Zn2_dhtp 窗口内 20 条 Cg···Cg 行中，涉及反演环的
12 条现逐行一致（Cg···Cg、两侧垂距 ≤0.01 Å，夹角 ≤0.5°，滑移 ≤0.01 Å）；另 8 条涉及
`find_rings` 不搜的 8 元并环，仍按 `size_outside_find_rings` 豁免。测试
`test_platon_ring_geometry_matches` 新增 `MIN_PIPI_COMPARED`（Zn2_dhtp ≥12），
让"豁免"不能再吞掉整张表。

**新增已知答案（R5-F）**：

- COD 2232050（Acta E67 o2762，三嗪鎓四氟硼酸盐）：作者摘要的 Cg1···F4ⁱ 3.178(3) Å、
  Cg1···F2ⁱ 3.654(3) Å（(i) 1−x, 2−y, 1−z）在引擎的 `anion_pi` 行算符下重量一致
  （±0.01 Å），引擎行本身量的是 B···Cg 3.720 Å / 偏移 0.70 Å；环与反演像的堆积
  d_cc 3.3362（作者 3.3361(12)）、垂距 3.3331（3.333）、滑移角 2.466°（2.46°）；
  5 条沉积氢键行全部复现。→ §7 里"阴离子–π 没有独立答案"关闭。
- COD 4115425（JACS 123, 743，Pt→Ag 螺旋链，P6₁）：`helices` 报 1 条一维片段、
  `6_1`、右手、螺距 = c = 41.608 Å、`racemic=False`。已知答案是对称推论
  （空间群 + 链沿 c），论文全文本机 403 未能核对螺距数字。

引文与下载命令见 `benchmark/known_answers/SOURCES.md`。
