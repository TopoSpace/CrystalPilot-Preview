# 互穿 MOF-5（双重穿插的 pcu）：已知答案来源

## 结构文件 `ref.cif`
- COD id **4324900** — <https://www.crystallography.net/cod/4324900.html>
  （`curl -s -m 60 -o ref.cif https://www.crystallography.net/cod/4324900.cif`）
- 文献：Kim, Das, Kim, Dybtsev, Kim, Kim, “Synthesis of Phase-Pure Interpenetrated MOF-5 and Its Gas Sorption Properties”, Inorg. Chem. 50 (2011) 3691
- DOI：10.1021/ic200054b
- 空间群 R-3 (:H)，a = 18.388, 18.388, 43.916 Å，T = 90(2) K，Z = 12，化学式 C24.99 H15.06 N0.33 O13.705 Zn4
- 客体状态：含 DEF/水客体（我们的宿主规则把 F2 C6H14N2O2 与 F3 O 判为客体并移除）；苯环有 A/B 两套 0.50 无序

## 拿来对照的文献值
- **双重（2-fold）互穿的 MOF-5**：两套 Zn4O(bdc)3 的 **pcu** 网互相
  穿插，标题即 “Phase-Pure **Interpenetrated** MOF-5”。
- 期望：`n_nets = 2`，两网都 dim = 3，`interpenetrated = True`，
  两网由 R-3 的**反演中心**相关（relation = `space_group_op`，
  op = `-x,-y,-z`），每个节点 6 连接，Systre 对两个分量都给 **pcu**。
- 合成对照（不需要任何下载）：把 MOF-5 的 P1 原子集加上它自己平移
  **(¼, ¼, ¼)** 的拷贝放进 P1，必须报 `interpenetrated=True`、
  relation = `translation`、shift = [0.25, 0.25, 0.25]。
  **注意**：(½,½,½) 不行，MOF-5 是 F 心格，(½,½,½) ≡ (0,0,½) mod F，
  正好把结构映回它自己（实测最近原子距离 0.000 Å），拷贝会与原子重合，
  得到的是"同一批原子写了两遍"，不是两张网。(¼,¼,¼) 的最近距离是
  3.67 Å，远在任何成键判据之上，两网真的互不接触地穿过。

## 许可
COD 条目按其文件头的条款使用（IUCr/作者授权，学术引用即可）；本目录只放
CIF 与本说明，不放任何二进制。
