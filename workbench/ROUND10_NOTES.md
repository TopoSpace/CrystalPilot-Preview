# Round 10 —— 专家知识采集与内化（DJ_Tokyo 语料）

用户指令：放弃阻塞数据源；把公众号 **Tokyo**（DJ_Tokyo，4081 篇单晶解析
专家心得）的干货全部下载为宝贵数据，练习数据一并收集，专门建档；用学到的
知识优化 CrystalPilot。追加线索：作者公布过获取渠道（doc88、物质结构社区
matstr.com 网盘分享帖）。B站视频暂不下载（占空间）。

## 采集战役

| 通道 | 结果 |
|---|---|
| matstr.com 论坛（Discuz） | **主通道**。作者 uid=103，全站 1449 帖中 1329 帖是他的（fid=12 单晶 66 页 + fid=30 资源 7 页 + fid=13 粉末 2 页）。游客可读正文；附件需登录（清单另记）。matstr_harvest.py 全量镜像：正文 HTML+MD+图片尝试+网盘链接/提取码提取 |
| 公众号短链 BFS | **主通道**。论坛帖正文的"参阅推文"是 mp.weixin.qq.com/s/<hash> 永久短链，公开可读无频控。seed_from_matstr.py 抽链 → crawl_links.py BFS（文章互引密集，自增殖；已挖到 2019 年老文）。seed+crawl 串行循环防状态竞态 |
| 搜狗搜索 | 降级停用：IP 被验证码墙标记（早期贡献 11 篇后连墙零产出）。matstr+BFS 覆盖后价值残余低 |
| doc88（1374 篇 PDF） | 放弃：游客态 AJAX 拿不到个人文档列表（截图 92 页列表应为登录态）；内容=公众号 PDF 版，标题被 B站 3028 全量覆盖，边际价值低 |
| B站 | 3028 视频标题元数据已存（videos.json）；视频本体按用户指示不下载 |

道客/搜狗接口细节、Discuz normalthread 行结构见 djtokyo/ 各脚本头注释。

## 知识内化（本轮已落地进仓库）

1. **审稿级孪晶统计检测器**（commit bf08a34）：真实 Acta 审稿案例
   （CCDC 2416519：Rint 5.25% + R1 7.28% 遭孪晶质疑；重测后 3.26/3.34
   即收）提炼出两条可计算判据，进 `audit_reflection_data`：
   - fcf 弱/中强度档 Fo²>Fc² 符号偏差（健康≈50%，≥65% 报警）
   - R1(obs) > 1.3×Rint 且 >5% 报"高于数据质量预期"，给出重测建议话术
2. **checkcif KB 修正+扩充**（commits 0356a5e, 后续）：61→71 条。
   **修正了 097/098 含义颠倒的既有错误**（Tokyo 案例实证 097=正峰）。
   新增 094/110/112/341/420/910/911(修)/913/971/972/973，条目带专家案例
   数值（探测器距离 39→60mm 治 910；换背景扣除治 971/973 的 2.6 e/Å³
   金属旁残峰；仅晶胞变换不重还原会多 65 个缺失反射被审稿人揪）。
   020 补 Rint 阈值（>0.10 C / >0.15 B / >0.20 A；实践 >18% 即 B）。
3. **estimate_resolution 双判据**：misigma=2.0 与 CC½ 并报（审稿人
   宽松档 I/σ≥2；严格档 I/σ≥3 写入 note）——"真实分辨率"审稿篇
   （Dalton Trans 案例：I/σ<3 于 2θ≈45° 处应截断并在实验部分注明）。
4. **专家案例卡库**（commit 118a52e）：`knowledge/expert-cases/` 3 张卡
   （PLAT097 分辨率截断数值链 / 高 R-孪晶四判据+重测决策 / Rint 还原
   策略两案例），AGENTS v14 增"专家案例库"节指引 agent 按症状检索。
5. **ASU 红旗徽章**（commit 0cf740d，r9 滚动项）：node commit 持久化
   asu_sanity → list_nodes 暴露计数 → 工作台节点行红色"⚠ 幽灵N 游离M"。

## 提炼管线（djtokyo/extracted-knowledge/）

- build_catalog.py：知识地图（当前 1348 条 16 类：无序-孪晶 235、
  CheckCIF-PLAT 181、审稿意见 115、晶体测试案例 151…）
- extract_plat.py：规则式 PLAT 摘要器（阈值行/解决策略行/指标链），
  输出 plat-digest.md 标注 KB 缺口——首轮 29 code/62 帖，全量后重跑
- case-cards/：案例卡 schema + 4 张卡（含 matstr 侧 3 张的仓库精选版）

## 未竟 / 交接

- matstr 全量镜像与 BFS 仍在跑（后台 bxkds9ebo / bo4ixa4iu）；跑完后：
  重跑 build_catalog + extract_plat 批量精编 KB；汇总 pan_links.md
  （练习数据网盘清单，需用户手动下载——**每个审稿意见帖都带论文
  PDF+CIF+原始数据链接**，93 帖≈93 套真实病例数据；另有 524 页
  《CheckCIF所有检测内容汇总及解释案例》PDF：
  pan.baidu.com/s/1R3vHy7mXnfgyBKz7HgH0-g 码 5p1k）
- 论坛附件（需登录）清单 attachments_login_needed.md 待收割完生成
- 公众号未被论坛/引用覆盖的孤立老文：用户配合方案（wechatDownload）
  仍是最终兜底，README-全量下载配合.md 已备
- 无序系列（235 帖）批量提炼成"无序处理规则集"（师兄重点）待全量后做

## 练习数据实战（用户下载 770/780 后的 E2E 战役）

**780 非预期结构**（43+14 节点，两轮）：agent 从误导性 C/H/N/O 先验独立
解出 [Al(μ-OH)(μ-HCOO)₂]ₙ（C2/c，R1 0.0537，结构侧 0A0B）——与评卷人
检索到的 CrystEngComm 2018（10.1039/c8ce00309b）同化合物，晶胞 1.2% 内。
空间群与文献分歧（C2 vs C2/c）触发深挖：发现 change_space_group 降群
门缺陷（标准 setting 算符匹配+闭合检查误拒真子群；且降群后不微扰=鞍点
永不分化）→ 修复（sgtbx.subgroups 母 setting 解析 + 0.03Å 确定性微扰）
→ agent 复验：C2 下禁戒子集仍失配（子集 R1 0.432、相关 0.26）+ 微扰后
弹回反演关联 → 裁决 C2 不成立、违例定性数据伪影。**没被 R1 下降诱惑**。

**770 孪晶-无序 La/Ni**（60+ 节点，第二轮进行中）：
- DIALS 帧路线发现 dxtbx 上游 bug（iotbx BrukerImage 硬编码 1024²，
  512² sfrm 数据进 1/4 象限）→ 写 FormatBrukerSfrmGeom 插件（真尺寸/
  2θ 倾转/反扫/原生溢出表解码）；但 D8 的 omega 轴向映射未逆向成功
  （SO(3) 网格无解，死因=轴向/坐标系复合），按用户指示转官方产物路线
- ingest_vendor_data 工具落地（SAINT/XPREP 产物冷启动）
- charge flipping 打不动 V=2475 大结构 → run_shelxt 工具落地
  （vendor SHELXT 正式集成，.lxt 解表）
- 第一轮成绩（vs COD 7135354 发表版）：晶胞/群/晶格苯/孪晶裁决全对；
  差距=4 组小占有率无序（112 位点）未建 + 由此 4 个 C→N 误判，
  R1 0.0666 vs 0.0553。GRADING.md 存逐项对照；第二轮按导师批改重建中

**770 第三轮**（PART 感知加氢修复后）：R1 0.0698→**0.0650**（发表
0.0553）；106 H（76 个进 PART，38+38 与发表版位点级完全一致）；组成
C48H68 vs 发表 C48H69——差的 1 个 H 是 C4 上的独立 H33，agent 因本数据
差图无对应峰而拒绝硬塞（正确的诚实裁决）；4 个 FVAR 自由精修，晶格苯
0.2825 vs 发表 0.2815 复现，另三组偏离 0.05-0.09（老实报告为剩余差距）。
agent 为绕过当时的工具缺陷用了"临时挪 P 原子哄骗分类器"的 hack 并如实
披露——由此揪出 #11/#12。

**过程暴露并修复的缺陷清单**：#1 中文路径 dxtbx 打不开（junction 的
cmd GBK 坑，改 python 复制）；#2 外部 hkl 冷启动缺口（ingest 工具）；
#4 sfrm 尺寸病理（插件）；#5 WMI rc 文件名冲突（uuid 后缀）；
#6 降群门+鞍点（子群解析+微扰）；#7 审批守护误伤提及哨兵文件名的
良性命令（AGENTS 明示别提及）；#8 求解器缺口（run_shelxt）；
#9 add_hydrogens PART 盲（几何连接把 A/B 备位当成互相成键→载体假饱和
→770 只放 26/69 H；修复=SHELX PART 语义过滤+H 继承占有率并挂进载体
disorder group 的 FVAR）；#10 rename_atoms 不联动 disorder_groups
（canonical 重标号后成员表存旧标签→8 个有序 C 误继承部分占有率——
agent 第三轮发现并手工纠正，引擎侧已补 _apply_rename_to_disorder）；
#11 键长合理性门硬编码 1.20-1.80 Å（P–C 1.86-1.90 全被拒→iPr 氢全丢；
修复=按元素对共价半径 0.78Σr..Σr+0.30，C–C 窗口不变）；#12 RefineLS
的 reparametrisation 连接表 PART 盲（幽灵 A↔B 邻居→骑乘约束
InvalidConstraint"bad connectivity"→agent 只能在 92/106 H 子集上精修；
修复=cctbx conformer_indices 原生表达 PART 语义，负 PART→
sym_excl_indices；inspect_model/geometry/viewer scene 的连接表同步
PART 感知）；#13 第四轮诚实失败报告暴露的一簇（根因=write_res 改名
>4 字符标签时只改 flags 不改活模型 → PART 成员查找落空 → 幽灵键回归
InvalidConstraint、RES 里 PART2 H 只剩 8/38。两层修复：add_hydrogens
生成 ≤4 字符 H 标签（长后缀退化为顺序编号）+ commit 把 rename 同步进
活模型与骑乘检查表。同簇：金属接触按共价半径和分 π/σ——π 接触（La···C
3.2Å）不挡质子化不占价、σ 键才受 include_metal_bonded 门管；线性 sp
碳门（≥160° 腈/炔不加 H）；add_atoms_from_difference_map 对
element='H' 用 0.70Å 距离下限——1.05Å 反噪声门曾拒绝一切真 X–H 峰）。
#14 第六轮定位的最后两项（adopt 用默认参数重放 add_hydrogens 吃掉
planar_sum_min=355 保住的 H16B→重放继承参数+丢失显式报警；inspect_map
深峰表不回存→与 add_atoms 统一峰表带 'i' 索引，refine 存 top-40）。
#9-#14 全部由 770 战役的真实失败暴露——练习数据测试循环按预期工作。

**770 终局（第七/八轮，n0185）**：组成 C48H69LaN4NiP2 Z=2、181 原子、
112 无序标记位点**全部与发表版一致**（结构层面完全闭合）；R1 0.0648 vs
0.0553（差距归因披露：三组占有率偏 0.05-0.08、完整度 74.1%、权重差异）；
H33 按差图证据（0.58 e/Å³）收进；CIF/RES 三方自洽；SAINT ._ls 元数据
装进 CIF 后 PLAT183/184/185 消失，checkCIF 7A→4A/2B/14C。七轮零手工
干预模型。已知小疣：长驻会话不自动刷新外部改动的 context.json（agent
以同值同步 CIF/REPORT 收尾）。
