# HKUST-1  Cu3(btc)2：已知答案来源

## 结构文件 `ref.cif`
- COD id **1546786** — <https://www.crystallography.net/cod/1546786.html>
  （`curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/1546786.cif`）
- 文献：Getzschmann, Senkovska, Wallacher, Tovar, Fairen-Jimenez, Düren, van Baten, Krishna, Kaskel, “Methane storage mechanism in the metal-organic framework Cu3(btc)2: An in situ neutron diffraction study”, Micropor. Mesopor. Mater. 136 (2010) 50
- DOI：10.1016/j.micromeso.2010.07.020
- 空间群 Fm-3m，a = 26.2824 Å，T = 77(2) K，Z = 16，化学式 C18 H6 Cu3 O12
- 客体状态：**无客体、无轴向水**：这是活化（脱溶剂、开放 Cu 位）的骨架本身，原子表只有 Cu/Oac/Ca/Cb/Cc/H

## 拿来对照的文献值
- **网：tbo**（RCSR）；Cu2 桨轮 **4 连接**、btc **3 连接**。来源：
  Chui, Lo, Charmant, Orpen, Williams, “A Chemically Functionalizable
  Nanoporous Material [Cu3(TMA)2(H2O)3]n”, Science **283** (1999) 1148,
  DOI 10.1126/science.283.5405.1148（结构本身）+ O'Keeffe & Yaghi 的
  RCSR：tbo 就是以 HKUST-1 为原型定义的 (3,4)-连接网。Systre 独立复核。
- **LCD ≈ 13.2 Å、PLD ≈ 6.9 Å**：这两个数在 Zeo++/CoRE-MOF 一系的高通量
  文献里被反复引用（Zeo++ 的 Di / Df，Willems, Rycroft, Kazi, Meza,
  Haranczyk, Micropor. Mesopor. Mater. **149** (2012) 134,
  DOI 10.1016/j.micromeso.2011.08.020 定义了这两个量）。
  **诚实说明**：本轮没有拿到写着"HKUST-1 = 13.2 / 6.9"的那一页原始表格，
  这两个数是任务书给的目标值；测试按 ±0.6 / ±0.8 Å 判定，报告里注明该值
  未经一手核对。

## 用作判据的实测值（本轮一手核对过）

统一口径：**CoRE MOF 2019 ASR**（Chung, Haldoupis, Bucior, … Snurr,
*J. Chem. Eng. Data* **64** (2019) 5985, DOI 10.1021/acs.jced.9b00835；
数据 Zenodo DOI 10.5281/zenodo.3677685，文件
`2019-11-01-ASR-public_12020.csv`），Zeo++ 高精度、去尽溶剂。

| refcode | LCD (Å) | PLD (Å) | AV_VF |
|---|---|---|---|
| `FIQCEN_clean`（HKUST-1） | **13.18983** | **6.65676** | 0.7206 |

第二意见：Sarkisov, Bueno-Perez, Sutharson, Fairen-Jimenez,
*Chem. Mater.* **32** (2020) 9849, DOI 10.1021/acs.chemmater.0c03575
随论文存放的实跑文件（<https://github.com/SarkisovGitHub/PoreBlazer>，
`PB4.0_vs_Zeo++_vs_RASPA.zip`，命令
`network -r uff.rad -ha -res X.res X.cif`，UFF 半径 C 1.7155 / H 1.2855）：
Zeo++ `HKUST1.res` = **12.99975 / 6.33766 / 12.99434**（Di / Df / Dif）；PoreBlazer v4.0 `summary.dat` PLD **6.38**、LCD **12.86**；同论文 12 000 结构表里的 FIQCEN = 6.35421 / 12.87967。

**注**：任务书给的 PLD “6.9 Å” 本轮**查不到出处**；能一手核到的实测值是 6.657 / 6.38 / 6.35（半径表不同）。


## 许可
COD 条目按其文件头的条款使用（IUCr/作者授权，学术引用即可）；本目录只放
CIF 与本说明，不放任何二进制。
