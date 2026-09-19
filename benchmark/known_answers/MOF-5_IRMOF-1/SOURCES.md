# MOF-5 / IRMOF-1  Zn4O(bdc)3：已知答案来源

## 结构文件 `ref.cif`
- COD id **1516287** — <https://www.crystallography.net/cod/1516287.html>
  （`curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/1516287.cif`）
- 文献：Lock, Wu, Christensen, Cameron, Peterson, Bridgeman, Kepert, Iversen, “Elucidating Negative Thermal Expansion in MOF-5”, J. Phys. Chem. C 114 (2010) 16181
- DOI：10.1021/jp103212z
- 空间群 Fm-3m，a = 25.8247 Å，T = 280(2) K，Z = 8，化学式 C24 H12 O13 Zn4
- 客体状态：**无客体**：脱溶剂后的骨架本身（原子表只有 Zn1/O1/O2/C1/C2/C3/H3），无需删任何原子

## 拿来对照的文献值
- **网：pcu**；Zn4O 簇 **6 连接**。来源：O'Keeffe & Yaghi 的网状化学
  （RCSR 符号 pcu），并可由 Systre 从我们的商图独立复核。
- **LCD / 小腔 / 孔口**：Li, Eddaoudi, O'Keeffe, Yaghi,
  “Design and synthesis of an exceptionally stable and highly porous
  metal-organic framework”, Nature **402** (1999) 276–279,
  DOI 10.1038/46248。原文（p. 279）逐字：
  > “The centre of the smaller of these has 24 H atoms at 7.10 Å and 24 C
  > atoms at 7.97 Å; the centre of the larger (Fig. 1) has 72 C atoms at
  > 9.26 Å and 48 H atoms at 9.47 Å. The aperture joining the two cavities
  > has 8 H at 5.10 Å and 8 C at 5.70 Å from its centre. Allowing for the
  > van der Waals radii, spheres of material with diameter 15.1 Å and 11.0 Å
  > could fit in the large and small cavities, respectively, and the
  > aperture would admit the passage of a sphere of diameter 8.0 Å.”

  即 **LCD = 15.1 Å**、小腔 11.0 Å、**孔口（PLD）= 8.0 Å**。
- 半径口径换算（重要）：上面的 15.1 / 8.0 用的是 r(C)=1.70、r(H)≈1.1–1.6。
  本平台的 `chem/pores.py` 用 `cctbx.eltbx.van_der_waals_radii`
  （C 1.775、H 1.20）。把 Nature 给出的**同一批距离**代进我们的半径：
  LCD = 2×(9.26 − 1.775) = **14.97 Å**；
  PLD = 2×min(5.70 − 1.775, 5.10 − 1.20) = **7.80 Å**。
  这两个数才是"同口径"的期望值，测试按它们判定，并同时列出 15.1 / 8.0。
- 溶剂可及体积：Nature 同页称 “55–61% of the space is accessible to guest
  spheres”（探针口径不同，仅作量级参照，不作判据）。

## 用作判据的实测值（本轮一手核对过）

CoRE MOF 2019 ASR（Chung et al., *J. Chem. Eng. Data* **64** (2019) 5985,
DOI 10.1021/acs.jced.9b00835；数据 Zenodo DOI 10.5281/zenodo.3677685）：

- `EDUSIF_clean`：LCD **15.05124**、PLD **7.91583**、AV_VF 0.8098
- `MIBQAR16_clean`：LCD 15.00006、PLD 7.9611、AV_VF 0.8098

第二意见（Sarkisov et al., *Chem. Mater.* **32** (2020) 9849 随论文存放的
Zeo++/UFF 与 PoreBlazer v4.0 实跑文件）：Zeo++ `IRMOF1.res` = **15.03334 / 7.77347 / 15.01697**；PoreBlazer v4.0 PLD **7.80** / LCD **15.03**；同论文 12 000 结构表里的 `SAHYIK`（另一次 MOF-5 测定）= PLD 7.66188 / LCD **14.91615**。


## 许可
COD 条目按其文件头的条款使用（IUCr/作者授权，学术引用即可）；本目录只放
CIF 与本说明，不放任何二进制。
