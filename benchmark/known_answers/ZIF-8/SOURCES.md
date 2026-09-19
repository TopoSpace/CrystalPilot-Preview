# ZIF-8  Zn(2-methylimidazolate)2：已知答案来源

## 结构文件 `ref.cif`
- COD id **7111973** — <https://www.crystallography.net/cod/7111973.html>
  （`curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/7111973.cif`）
- 文献：Shekhah, Swaidan, Belmabkhout, du Plessis, Jacobs, Barbour, Pinnau, Eddaoudi, “The liquid phase epitaxy approach for the successful construction of ultra-thin and defect-free ZIF-8 membranes: pure and mixed gas transport study”, Chem. Commun. 50 (2014) 2089 （COD commonname: ZIF8Vacuum）
- DOI：10.1039/c3cc47495j
- 空间群 I-43m，a = 17.033 Å，T = 298(2) K，Z = 12，化学式 C8 H10 N4 Zn
- 客体状态：**抽真空后的空骨架**（COD commonname `ZIF8Vacuum`）。甲基 H（H3A/H3B/H3C）各占 0.50，三个转动异构位置**同时在模型里**：几何计算会把三个都当实体，见报告

## 拿来对照的文献值
- **网：sod**；Zn **4 连接**。
- **腔 11.6 Å、孔口 3.4 Å**：Park, Ni, Côté, Choi, Huang, Uribe-Romo, Chae,
  O'Keeffe, Yaghi, “Exceptional chemical and thermal stability of zeolitic
  imidazolate frameworks”, PNAS **103** (2006) 10186,
  DOI 10.1073/pnas.0602439103：ZIF-8 与 ZIF-11 “possess large pores
  (11.6 and 14.6 Å in diameter for ZIF-8 and -11, respectively) connected
  through small apertures (3.4 and 3.0 Å across ...)”。
- 该文的 3.4 Å 是**静态晶体学孔口**，同文与后续文献都强调 ZIF-8 有
  “gate-opening” 柔性，动力学上并不在 3.4 Å 截止。

## 用作判据的实测值（本轮一手核对过）

CoRE MOF 2019 ASR（Chung et al., *J. Chem. Eng. Data* **64** (2019) 5985,
DOI 10.1021/acs.jced.9b00835；数据 Zenodo DOI 10.5281/zenodo.3677685）：

- `VELVOY_clean`（即 Park 2006 那套结构）：LCD **11.39286**、PLD **3.40894**、AV_VF 0.625

第二意见（Sarkisov et al., *Chem. Mater.* **32** (2020) 9849 随论文存放的
Zeo++/UFF 与 PoreBlazer v4.0 实跑文件）：Zeo++ `ZIF8.res` = **11.39850 / 3.07308 / 11.39850**；PoreBlazer v4.0 PLD **2.86** / LCD **11.42**。同一材料三种口径给 2.86 / 3.07 / 3.41，PNAS 的 3.4 落在上沿。


## 许可
COD 条目按其文件头的条款使用（IUCr/作者授权，学术引用即可）；本目录只放
CIF 与本说明，不放任何二进制。
