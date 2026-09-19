# UiO-66  Zr6O4(OH)4(bdc)6：已知答案来源

## 结构文件 `ref.cif`
- COD id **4132633** — <https://www.crystallography.net/cod/4132633.html>
  （`curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/4132633.cif`）
- 文献：Lee, Bürgi, Alshmimri, Yaghi, “Impact of Disordered Guest-Framework Interactions on the Crystallography of Metal-Organic Frameworks”, J. Am. Chem. Soc. 140 (2018) 8958
- DOI：10.1021/jacs.8b05271
- 空间群 Fm-3m，a = 20.7123 Å，T = 100.15 K，Z = 4，化学式 C42.7 H25.4 O32.04 Zr6
- 客体状态：**没有独立客体分子**，但这是一个**有缺陷的**沉积模型：连接子（O3/C1/C2/C3/H3）占有率 0.89（缺连接子缺陷），μ3-O 与 μ3-OH 以 O1/O2 两套位置各占 0.50 拆分（外加 H2 占 0.50）。几何计算按全占把两套 μ3 氧都算进去（两者相距约 0.47 Å，互相重叠），并把 32 个 μ3-OH 的 H 全部计入，见报告的口径说明

## 拿来对照的文献值
- **网：fcu**；Zr6 簇 **12 连接**。来源：Cavka, Jakobsen, Olsbye,
  Guillou, Lamberti, Bordiga, Lillerud, “A New Zirconium Inorganic Building
  Brick Forming Metal Organic Frameworks with Exceptional Stability”,
  J. Am. Chem. Soc. **130** (2008) 13850, DOI 10.1021/ja8057953。
- 腔/窗口的常引值（**标称、未做 vdW 修正**）：八面体腔 ~11 Å、
  四面体腔 ~8 Å、三角窗口 ~6 Å（同上文献及大量后续综述）。
  减去两个 vdW 半径后与硬球口径可比：11 − 2×1.2 ≈ **8.6 Å**（≈ LCD），
  6 − 2×1.2 ≈ **3.6 Å**（≈ PLD）。任务书给的目标是 LCD ≈ 8.5、PLD ≈ 4。
- **诚实说明**：本轮没有拿到一份写着 UiO-66 的 Zeo++ LCD/PLD 数值的
  一手表格；对照用的是上面的标称腔/窗口值 + vdW 修正，以及任务书目标值。

## 用作判据的实测值（本轮一手核对过）

统一口径：**CoRE MOF 2019 ASR**（Chung, Haldoupis, Bucior, … Snurr,
*J. Chem. Eng. Data* **64** (2019) 5985, DOI 10.1021/acs.jced.9b00835；
数据 Zenodo DOI 10.5281/zenodo.3677685，文件
`2019-11-01-ASR-public_12020.csv`），Zeo++ 高精度、去尽溶剂。

| refcode | LCD (Å) | PLD (Å) | AV_VF |
|---|---|---|---|
| `RUBTAK04_clean` | **8.73929** | **3.8669** | 0.5686 |
| `RUBTAK05_clean` | 8.72137 | 3.8551 | 0.5676 |
| `RUBTAK06_clean` | 8.7342 | 3.8432 | 0.5664 |
| `RUBTAK07_clean` | 8.72079 | 3.85677 | 0.5662 |
| `RUBTAK08_clean` | 8.7506 | 3.87613 | 0.5644 |
| `RUBTAK09_clean` | 8.7392 | 3.86679 | 0.5678 |
| `RUBTAK01_SL` | 8.70379 | 4.00842 | 0.5914 |
| `RUBTAK02_SL` | 8.49537 | 3.88559 | 0.5866 |

第二意见：Sarkisov, Bueno-Perez, Sutharson, Fairen-Jimenez,
*Chem. Mater.* **32** (2020) 9849, DOI 10.1021/acs.chemmater.0c03575
随论文存放的实跑文件（<https://github.com/SarkisovGitHub/PoreBlazer>，
`PB4.0_vs_Zeo++_vs_RASPA.zip`，命令
`network -r uff.rad -ha -res X.res X.cif`，UFF 半径 C 1.7155 / H 1.2855）：
Zeo++ 对 `RUBTAK02` 给 **3.85049 / 8.96602**；PoreBlazer v4.0 给 PLD **3.69** / LCD **8.90**。

**同一种材料在同一个库里 LCD 就从 8.49 跨到 8.97 Å**：这正是 ±0.6 Å 判据的来由。


## 许可
COD 条目按其文件头的条款使用（IUCr/作者授权，学术引用即可）；本目录只放
CIF 与本说明，不放任何二进制。
