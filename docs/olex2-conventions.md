# Olex2 显示/交互约定调研（round 7，用于 CrystalViewer 设计）

来源：olexsys.org 文档、Olex2 帮助仓库、Guzei/Northwestern 教程（2026-08-29 调研）。
已落地项标 ✅（scene.py v3 + CrystalViewer），未落地项为后续迭代候选。

## 显示样式
- 样式集：pers（球棍）/ telp（椭球）/ tubes / sfil（空间填充）/ poly。
- ✅ 椭球：`telp 50` = **50% 概率**是标准（ORTEP 约定）；各向异性→椭球，
  各向同性→球，H→小固定球（`telph` 则按 Uiso 缩放，我们采用了这个：
  iso 原子画 1.538·√U_eq 的 50% 概率球）。
- `ads ort` = 八分之一切角椭球（ORTEP 挖角画法），未做，纯装饰。
- 键：半径 0.1 Å（brad 1），**半键着色**（各半取相邻原子元素色），3Dmol
  stick 天然如此 ✅；出版图常用 brad 0.3 + H 球 arad 0.08。
- 元素色 CPK；画布可开图例。✅ 我们统一用 Jmol 色表（3Dmol 默认表缺 W
  等重元素会掉到 DeepPink，已修）。

## grow 语义（我们的 grow 模式对标）
- `grow`：按对称算符补全跨 ASU 的成键连通性；算符"只差平移"即停
  （聚合物长出一大块而不无限）。`grow -s` = 只长第一配位壳。
  `grow -w` = 对未成键 moiety 重用已用算符（补溶剂化学计量）。
- `mode grow`（Ctrl+G）：显示**可点击的虚线 grow 键**，点一根就对整个
  成键片段应用该算符；`-v` 显示 vdW 半径和 +2.0 Å 内最短接触方向的
  唯一算符；接触 grow 键画成**粉色虚线**。
  → 未来候选：viewer 里画 dangling grow stub（点击后请求 server 扩展
  scene，需要 per-frontier-op 的增量 scene API）。
- `fuse` 回到 ASU；`compaq` 围绕最大片段组装；`move` 收进晶胞。

## 标签/其他
- ✅ 标签默认关，F3 开非 H 标签（我们做成"标签"开关）。
- ✅ 对称生成原子：`label -symm` 上标算符 id（我们在选中卡显示 symop 串）。
- ✅ 氢键 `htab`：D···A ≤ 2.9 Å、角 ≥150°、供受体 N/O/F/Cl/S；画
  1/10 键半径的细虚线（我们 0.02 Å 粉虚线，无 H 时不设角度门）。
- 晶胞默认关（我们默认开，带标注的 a,b,c 轴是未来候选）；`basis` 小部件。
- 无序：showp 按 PART 过滤显示，候选（scene 需带 part 字段）。

## 交互
- ✅ 点原子=选中；**2/3/4 连点=距离/角度/二面角**（esd 需协方差矩阵，
  服务端才有，目前客户端只报数值）。
- 双击=选整分子；Esc=清选/退模式；Ctrl+H 切 H；Ctrl+G grow 模式。
- 旋转 LMB / 面内旋转 Ctrl+LMB / 缩放 RMB / 平移 Ctrl+Shift+LMB（3Dmol
  自带手势即可）。
- `mpln -n` 最小二乘平面平行屏幕的自动取向，好的"重置视角"升级候选。

## 后续迭代排序建议
1. grow stub 交互（点虚线键长片段）→ 需增量 scene API
2. PART 无序显示过滤 + 占位/PART 标签模式
3. 晶胞轴 a/b/c 标注 + basis 部件
4. 出版级样式预设（brad 0.3、白底、挖角椭球、POV 导出）
