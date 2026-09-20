/** Strings for lib/toolCards.tsx: tool card titles, chips and summaries.
 *  `en` is typed against `zh`: both must carry the same keys. */

export const zh = {
  // shared chips and joiners
  nodeChip: (node: string) => `节点 ${node}`,
  atomsCount: (n: number | string) => `${n} 原子`,
  cellChip: (abc: string) => `晶胞 ${abc} Å`,
  atomFallback: "原子",
  listSeparator: "；",
  completenessPct: (v: string | number) => `完整度 ${v}%`,
  completenessValue: (v: string) => `完整度 ${v}`,
  uniqueCount: (n: string) => `${n} 独立`,
  expectedElectrons: (v: string) => `期望 ${v}e`,
  notTested: (n: number) => `未测 ${n}`,
  notTestedBudget: (n: number) => `未测 ${n}（预算）`,
  baselineChip: (node: string) => `基线 ${node}`,
  budgetExceededWarn: "超出时间预算：未测候选已列出，再调一次即可",
  eStatsCentro: "E 统计偏心",
  eStatsNonCentro: "E 统计偏非心",

  // label tables
  refineModes: {
    isotropic: "各向同性",
    anisotropic: "各向异性",
    scale_only: "仅标度",
  } as Record<string, string>,
  specialties: {
    space_group: "空间群",
    chemistry: "化学建模",
    density: "残余密度",
    validation: "结构验证",
    refinement_strategy: "精修策略",
  } as Record<string, string>,
  confidence: {
    high: "高",
    medium: "中",
    low: "低",
  } as Record<string, string>,
  views: {
    a: "沿 a 轴",
    b: "沿 b 轴",
    c: "沿 c 轴",
    oblique: "斜视",
  } as Record<string, string>,
  states: {
    asu: "不对称单元",
    cell: "单胞（P1 展开）",
    supercell: "2×2×2 堆积",
  } as Record<string, string>,
  tierLabels: {
    unmet: "未达",
    met: "已达",
    not_applicable: "不适用",
  } as Record<string, string>,

  // rendered views
  viewOpenFull: "点击查看原图",

  // refine
  refineRunning: (mode: string | undefined) => `正在最小二乘精修${mode ? `（${mode}）` : ""}…`,
  refineDone: "精修完成：",
  refineWithMask: "，含溶剂掩膜",
  residualPeak: (v: string) => `残差 ${v} eÅ⁻³`,

  // run_shelxl
  shelxlRefineRunning: "正在进行 SHELXL 精修…",
  shelxlCrossRunning: "正在运行 SHELXL 交叉验证…",
  disorderRevoke: (n: number) => `无序 ${n} 组应撤销`,
  disorderUndecided: (n: number) => `无序 ${n} 组未定`,
  disorderMeasurable: (n: number) => `无序 ${n} 组占比可测`,
  siteOccupancy: (atom: string, value: string, su: string | undefined) =>
    `${atom} 占有率 ${value}${su === undefined ? "（s.u. 未定）" : ` ± ${su}`}`,
  shelxlRefine: "SHELXL 精修",
  shelxlCross: "SHELXL 交叉验证",
  metricsMissing: "指标摘要未保留",
  shelxlDelta: (d: string, agrees: boolean) => `（Δ ${d}，${agrees ? "一致" : "分歧"}）`,
  shelxlTitle: (label: string, r1: string, delta: string) => `${label}：${r1}${delta}`,
  shelxlNoSummary: "当前记录没有完整的精修摘要；请展开原始结果，或查看该次精修节点的指标。",

  // fit_fragment / add_atoms_from_difference_map / edit_atoms / add_hydrogens
  fitFragmentRunning: "正在按配体模板拟合原子…",
  fitFragmentTitle: (n: number) => `按配体模板补入 ${n} 个原子`,
  fitFragmentRefused: (n: number) => `拒绝 ${n} 个（密度不支持）`,
  addFromMapRunning: "正在从差值图挑选峰位补原子…",
  addFromMapTitle: (n: number) => `从差值图补入 ${n} 个原子`,
  editAtomsRunning: "正在编辑模型…",
  editAtomsTitle: (n: number) => `编辑模型（${n} 项操作）`,
  addHRunning: "正在添加骑乘氢…",
  addHTitle: (n: number, elements: string[]) =>
    `添加 ${n} 个骑乘氢${elements.length > 0 ? `（${elements.join("、")}）` : ""}`,
  carriers: (n: number) => `载体 ${n}`,

  // optimize_weights / solvent_mask
  optimizeWeightsRunning: "正在优化权重方案…",
  weightsOptimized: "权重优化：",
  solventMaskRunning: "正在计算溶剂掩膜…",
  solventMaskTitle: (n: number, electrons: number | undefined) =>
    `溶剂掩膜：${n} 个孔洞${electrons !== undefined ? ` · ~${electrons} e⁻` : ""}`,
  solventVolume: (pct: string) => `溶剂体积 ${pct}%`,

  // search_fragment_pose / accept_fragment_pose
  searchPoseRunning: "正在搜索整片段姿态…",
  searchPoseTitle: (n: number, formula: string | undefined) => {
    const tail = formula ? `（${formula}）` : "";
    return n === 0 ? `片段姿态搜索：无候选${tail}` : `片段姿态搜索：${n} 个候选${tail}`;
  },
  searchPoseTop: (id: string, direct: number, weak: number, geo: number) =>
    `首选 ${id} · 直接峰 ${direct} · 弱密度 ${weak} · 仅几何 ${geo}`,
  searchPoseFolded: (n: number) => `对称折叠 → ${n} 个独立原子`,
  searchPoseGeoOnly: (n: number) => `${n} 个原子只有几何支持，密度不支持`,
  acceptPoseRunning: "正在把候选片段收入模型…",
  acceptPoseTitle: (id: string, n: number) => `接受片段候选 ${id}：加入 ${n} 个原子`,
  occupancyChip: (v: string) => `占有率 ${v}`,

  // set_restraints / preflight_restraints
  setRestraintsRunning: "正在更新约束…",
  setRestraintsTitle: (action: string, n: number) => `约束 ${action}：现有 ${n} 条`,
  restraintsCrossPart: (n: number) => `${n} 项跨非零 PART，SHELXL 不会施加`,
  preflightRunning: "正在预检约束…",
  preflightCount: (n: number) => `${n} 条`,
  preflightCrossPart: (n: number) => `跨 PART ${n} 项`,
  preflightNotRepresentable: (n: number) => `不可表达 ${n} 项`,
  preflightWarnings: (n: number) => `提示 ${n} 条`,
  preflightTitle: (parts: string) => `约束预检：${parts}`,
  preflightCrossPartWarn: (n: number) => `SHELXL 不施加跨非零 PART 的距离/平面约束（${n} 项）`,

  // branch / checkout
  branchRunning: "正在新建分支…",
  branchTitle: (branch: string, at: string) => `新建分支 ${branch}（自 ${at}）`,
  checkoutRunning: "正在检出节点…",
  checkoutTitle: (node: string, branch: string | undefined) =>
    `检出 ${node}${branch !== undefined ? `（${branch}）` : ""}`,

  // checkCIF
  iucrRunning: "正在提交 IUCr 官方 checkCIF…",
  iucrPrefix: "IUCr 官方 checkCIF",
  checkcifCounts: (prefix: string, a: number, b: number, c: number) =>
    `${prefix}：A×${a} · B×${b} · C×${c}`,
  checkcifSalvaged: (prefix: string, parts: string | null) => `${prefix}：${parts ?? "已完成"}`,
  checkcifTruncated: "结果尾部被截断，仅恢复部分警报；完整列表见右侧「验证」页",
  checkcifUnparsed: (prefix: string) => `${prefix} 完成（结果不可解析，见「验证」页）`,

  // consult_specialist
  consultRunning: (specialty: string) => `正在咨询${specialty}专家…`,
  toolCalls: (n: number) => `${n} 次工具调用`,
  consultTitle: (specialty: string) => `专家咨询（${specialty}）完成`,
  confidenceChip: (label: string) => `置信度 ${label}`,
  recommendationLabel: "建议：",
  evidenceLabel: "证据：",
  risksLabel: "风险：",

  // check_symmetry
  checkSymmetryRunning: "正在审计空间群对称性…",
  checkSymmetryDone: "对称性审计完成",
  currentSg: (sg: string) => `当前 ${sg}`,
  suggestedSg: (sg: string) => `建议 ${sg}`,
  metricPseudoSymmetry: "晶格存在赝对称",
  extraSymmetryWarn: "模型服从额外对称操作，需在更高对称群中重精修验证，并如实披露",

  // rename_atoms
  renameRunning: "正在规范重标号…",
  renameNoChange: "原子标号已规范，无需重命名",
  renameTitle: (n: number) => `规范重标号 ${n} 个原子`,

  // import_cif_model
  importCifRunning: "正在导入外部 CIF 结构…",
  importCifTitle: (atoms: number | string, sg: string) => `导入外部结构：${atoms} 原子，空间群 ${sg}`,
  anisoCount: (n: number) => `各向异性 ${n}`,
  conversionNotes: (n: number) => `${n} 条转换说明（展开技术详情查看）`,

  // raw frames pipeline (DIALS)
  importFramesRunning: "正在导入衍射帧…",
  importFramesTitle: (n: number | string, sweeps: number | undefined) =>
    `导入衍射帧：${n} 张图像${sweeps !== undefined ? `（${sweeps} 个扫描）` : ""}`,
  backgroundFrames: (n: number) => `本底 ${n}`,
  findSpotsRunning: "正在寻找衍射斑点…",
  findSpotsTitle: (n: string) => `寻峰：${n} 个强斑点`,
  indexRunning: "正在指标化…",
  indexTitle: (n: string, pct: number | undefined) =>
    `指标化：${n} 个反射${pct !== undefined ? `（${pct}%）` : ""}`,
  indexLowWarn: "指标化率偏低，晶胞/取向可能有误",
  integrateRunning: "正在积分强度…",
  integrateTitle: (n: string) => `积分：${n} 个反射`,
  scaleRunning: "正在标定并导出…",
  scaleTitle: (parts: string | null) => `标定导出${parts ? `：${parts}` : "完成"}`,
  resolutionChip: (d: number) => `分辨率 ${d} Å`,
  uniqueReflections: (n: string) => `独立反射 ${n}`,
  suggestedSpaceGroup: (sg: string) => `建议空间群 ${sg}`,
  startModelRunning: "正在构建初始模型…",
  startModelTitle: (n: number | string, r1: string) => `初始模型：${n} 原子（粗解 R1 ${r1}）`,

  // finalize_delivery
  finalizeRunning: "正在封存交付…",
  deliveryDiagnosticSealed: "诊断性交付已封存",
  deliveryFinal: "交付已定稿",
  deliveryTitle: (status: string) => `交付：${status}`,
  statusUnreported: "状态未报告",
  waivedCount: (n: number) => `豁免 ${n} 项`,
  waivedWarn: "有豁免项：理由已记入 REPORT.json，报告里须逐条说明",

  // ghost_test / element_scan / probe_site
  ghostRunning: (n: number | string) => `正在做幽灵原子批量测试（${n} 个）…`,
  ghostTitle: (n: number, real: number, ghost: number, inconclusive: number) =>
    `幽灵测试：${n} 个原子，真 ${real} / 幽灵 ${ghost} / 不定 ${inconclusive}`,
  elementScanRunning: (site: string) => `正在扫描 ${site} 的候选元素…`,
  siteFallback: "位点",
  elementScanTitle: (n: number, top: string, tied: string[]) =>
    `元素扫描：${n} 个候选，证据首位 ${top}${tied.length > 1 ? `（并列：${tied.join("/")}）` : ""}`,
  notReadyCount: (n: number) => `未就绪 ${n}`,
  ready: "就绪",
  elementScanBlocked: (blockers: string) => `R 差在此模型上无意义：${blockers}`,
  elementScanHint: "元素由化学定（配位数/键长/簇型/吸收边），R 只是旁证",
  probeRunning: (what: string) => `正在试建 ${what}（占有率自由精修）…`,
  candidateAtomFallback: "候选原子",
  probeTitle: (n: number, supported: number, notSupported: number, borderline: number) =>
    `低占有试建：${n} 个候选，支持 ${supported} / 不支持 ${notSupported} / 临界 ${borderline}`,
  probeOccupancy: (element: string, occ: string, e: string | undefined) =>
    `${element} 占有 ${occ}${e !== undefined ? `（${e} e）` : ""}`,
  maskOffInVoid: "掩膜已关（位点在空腔内）",
  probeHint: "占有率×Z 才是数据钉住的量：低占有重原子只有几个电子，别拿满占有电子数当尺子",

  // write_outputs / fourier_complete
  writeOutputsRunning: "正在写出成果文件…",
  writeOutputsTitle: (n: number, publication: boolean) =>
    `输出 ${n} 个成果文件${publication ? "（发表级 CIF+fcf）" : ""}`,
  fourierRunning: "正在做傅里叶补全…",
  fourierTitle: (n: number) => `傅里叶补全：补入 ${n} 个原子`,

  // observe tools
  briefRunning: "正在读取项目简报…",
  briefTitle: "读取项目简报",
  inspectModelRunning: "正在查看模型…",
  inspectModelTitle: (n: number | undefined) => `查看模型${n !== undefined ? `（${n} 原子）` : ""}`,
  suspectAtoms: (n: number) => `可疑原子 ${n}`,
  isolatedAtoms: (n: number) => `孤立原子 ${n}`,
  inspectMapRunning: "正在检查差值密度…",
  inspectMapTitle: "检查差值密度",
  checkLigandRunning: "正在比对配体模板…",
  checkLigandTitle: "比对配体",
  geometryRunning: "正在生成几何表…",
  geometryTitle: (nb: number, na: number, esd: boolean, truncated: boolean) =>
    `几何表：${nb} 键 ${na} 角${esd ? "（含 SHELXL esd）" : "（无 esd）"}${truncated ? "，已截断" : ""}`,
  packingRunning: "正在生成堆积 / 孔道 / 相互作用测量表…",
  packingTitle: (nIx: number, nV: number, pi: string | undefined, cards: number) =>
    `堆积分析：相互作用 ${nIx} 行 · 孔道 ${nV}${pi !== undefined ? ` · 堆积 ${pi} %` : ""}${cards ? ` · HTAB 卡 ${cards}` : ""}`,
  validateRunning: "正在做结构验证…",
  validateTitle: (n: number) => `结构验证：${n} 项提醒`,
  auditReflRunning: "正在体检反射数据（孪晶/对称性征兆）…",
  auditReflTwin: (n: number) => `反射数据体检：孪晶警示征 ×${n}`,
  auditReflClean: "反射数据体检：无孪晶/对称性征兆",
  auditReflHints: (n: number) => `反射数据体检：${n} 条提示`,
  integrateDensityRunning: "正在积分区域残差电子数…",
  modelClaims: (v: string) => `模型声称 ${v}e`,
  integrateDensityTitle: (bits: string | null) => `残差电子数积分${bits ? `：${bits}` : ""}`,
  auditElementRunning: "正在审计 C/N/O 元素指认证据…",
  auditElementTitle: (n: number, idle: number) => `元素指认证据：${n} 处需判读（闲置 N/O ×${idle}）`,
  auditElementClean: "元素指认证据：无异常信号",

  // data ingest / reduction
  ingestRunning: "正在摄入厂商数据…",
  ingestTitle: (hkl: string) => `摄入厂商数据：${hkl}`,
  hklf5Domains: (n: number | string) => `HKLF5 · ${n} 域`,
  crysalisRunning: "正在用 CrysAlisPro 还原数据（峰搜 / 索引 / 积分）…",
  crysalisTitle: (n: string) => `CrysAlisPro 还原完成：${n} 行反射`,
  stepsCount: (n: number) => `${n} 步`,
  estimateResRunning: "正在评估分辨率截断证据…",
  estimateResNone: "分辨率评估：无 shell 达标（数据弱或已合并）",
  estimateResTitle: (d: string, cur: string | undefined) =>
    `分辨率评估：建议 d_min ${d} Å${cur === undefined ? "" : `（当前 ${cur}）`}`,
  shellsCount: (n: number) => `${n} 壳层`,
  latticeChip: (c: string) => `点阵 ${c}`,
  exportHklf5Running: "正在导出双域 HKLF5 数据…",
  exportHklf5Title: (composites: string, clean: string) =>
    `导出 HKLF5：${composites} 复合 · ${clean} 主域净反射`,
  reusedIntegration: "复用积分缓存",
  swapRunning: (hkl: string) => `正在换用反射数据 ${hkl}…`,
  swapTitle: (to: string, hklf: number | string, domains: number | undefined) =>
    `换用数据：${to}（HKLF${hklf}${domains === undefined ? "" : ` · ${domains} 域`}）`,
  observations: (n: string) => `${n} 观测`,
  setExperimentRunning: "正在登记实验元数据…",
  setExperimentTitle: (fields: string | null) => `登记实验元数据：${fields ?? "（无）"}`,
  removedCount: (n: number) => `删除 ${n} 项`,
  removeAbsent: (keys: string) => `请求删除但不存在：${keys}`,

  // structure solution
  chargeFlipRunning: "正在电荷翻转求解…",
  chargeFlipTitle: (corr: string, n: number | string) => `电荷翻转求解：图相关 ${corr} · ${n} 个峰`,
  seedChip: (n: number) => `种子 ${n}`,
  superflipRunning: "正在用 Superflip 求解…",
  superflipTitle: (r: string, n: number | string) => `Superflip 求解：R ${r}% · ${n} 个峰`,
  symmetryAgreement: (v: string) => `对称一致性 ${v}`,
  cyclesCount: (n: number) => `${n} 轮`,
  superflipSymWarn: "密度不遵守假定的对称算符，空间群存疑，先查对称再继续",
  shelxtRunning: "正在用 SHELXT 双空间求解…",
  shelxtAdoptedTitle: (sg: string, n: number | string) => `SHELXT 求解并采纳：${sg} · ${n} 原子`,
  shelxtTitle: (n: number) => `SHELXT 求解：${n} 个候选（未采纳）`,
  bestChip: (sg: string) => `最佳 ${sg}`,
  interpretRunning: "正在把峰列表解释为原子…",
  interpretTitle: (n: number | string, comp: string) => `解释峰为原子：${n} 个${comp ? `（${comp}）` : ""}`,
  symmetryGhostsRemoved: (n: number) => `剔对称幽灵 ${n}`,
  compositionUnknown: "组成未知",
  unassignedHeavyWarn: (n: number) => `${n} 个疑似未指认重原子位，元素指认可能有误`,

  // symmetry
  screenSgRunning: "正在筛查候选空间群…",
  screenSgTitle: (sg: string, n: number, total: number | string) => `空间群筛查：首选 ${sg}（${n}/${total} 候选）`,
  violationRate: (v: string) => `违背率 ${v}%`,
  auditHeavyRunning: "正在审计重原子位点…",
  auditHeavyTitle: (n: number | string, ready: boolean) =>
    `重位点审计：${n} 个位点，R-vs-Z ${ready ? "可做" : "未就绪"}`,
  absorptionEdges: (edges: string) => `吸收边：${edges}`,
  blockersCount: (n: number) => `阻碍 ${n}`,
  reflStatsRunning: "正在统计反射数据…",
  reflStatsTitle: (laue: string, n: string) => `反射统计：${laue} 类，${n} 独立`,
  fileCentring: (c: string) => `文件含 ${c} 心`,
  laueScan: (n: number) => `劳厄扫描 ${n} 类`,
  changeSgRunning: (sg: string) => `正在改用空间群 ${sg}…`,
  declareSgTitle: (sg: string) => `声明空间群：${sg}`,
  changeSgTitle: (from: string, to: string) => `改换空间群：${from} → ${to}`,
  atomsDelta: (from: number, to: number) => `原子 ${from} → ${to}`,
  opsVerified: (n: number) => `新增算符 ${n} 已验证`,
  hStripped: (n: number) => `剥氢 ${n}`,
  droppedState: (items: string) => `丢失会话状态：${items}（需重建）`,
  ncsRunning: "正在审计赝对称（平移/反演假设）…",
  ncsTitle: (inversion: boolean, pct: string) => `赝对称审计：${inversion ? "反演" : "平移"}假设匹配 ${pct}%`,
  ncsTitlePlain: "赝对称审计",
  rationalOperator: "算符落在有理分数",
  ncsWarn: "强匹配 + 有理算符 = 可能漏了晶体学对称，先查对称/怀疑晶胞",
  assembleRunning: "正在装配连贯的不对称单元…",
  asuCoherent: (n: number | string) => `ASU 已连贯（${n} 个碎片）`,
  asuDryRun: (steps: number, before: number | string) => `ASU 装配预演：${steps} 步（离散原子 ${before}）`,
  asuAssembled: (steps: number, before: number | string, after: number | string) =>
    `装配 ASU：${steps} 步，离散原子 ${before} → ${after}`,
  occupancyRescaled: (n: number) => `占据重标 ${n}`,
  ghostSuspects: (n: number, labels: string) => `仍有 ${n} 个幽灵原子嫌疑：${labels}`,

  // refinement / twin state
  olex2Running: "正在用 olex2.refine 独立复核…",
  olex2Title: (r1: string) => `olex2 独立复核：R1 ${r1}`,
  deltaVsSession: (d: string) => `与本会话差 ${d}`,
  setWeightsRunning: "正在设置权重方案…",
  setWeightsTitle: (from: string, to: string) => `设置权重 WGHT：${from} → ${to}`,
  removeResRunning: "正在移除分辨率截断…",
  setResRunning: (d: string | number) => `正在设置分辨率截断 d_min ${d}…`,
  removeResTitle: "移除分辨率截断（恢复全分辨率）",
  setResTitle: (shel: string) => `分辨率截断：${shel}`,
  setZRunning: "正在设置 Z 值…",
  setZTitle: (from: number | string, to: number | string, zPrime: string) =>
    `设置 Z：${from} → ${to}（Z' ${zPrime}）`,
  groupOrder: (n: number) => `群阶 ${n}`,
  undoDisorderRunning: (undo: string) => `正在撤销无序拆分（${undo}）…`,
  splitDisorderRunning: (atoms: string) => `正在拆分无序位点${atoms ? `（${atoms}）` : ""}…`,
  undoDisorderTitle: (undone: string, n: number) => `撤销无序拆分 ${undone}：${n} 对合并回单一位点`,
  deletedAtoms: (labels: string) => `删除 ${labels}`,
  fvarRenumbered: "FVAR 重新编号",
  restraintsPruned: (n: number) => `同时清理了 ${n} 条指向被删原子的限制`,
  splitDisorderTitle: (n: number) => `拆分无序：${n} 个位点（PART 1/2，占比待 SHELXL 精修判定）`,
  occupancyAStart: (v: string) => `A 占据 ${v}（起始值）`,
  restraintSuggestion: "附 SADI/SIMU 建议",
  bSitesFolded: (n: number) => `${n} 个 B 位点经对称折算到胞内`,
  twinSuggestRunning: "正在列举可能的孪晶定律…",
  twinRemoveRunning: "正在移除孪晶设置…",
  twinSetRunning: "正在设置孪晶定律…",
  twinCandidatesTitle: (n: number) => `孪晶定律候选：${n} 条（未应用）`,
  listOnly: "仅列举",
  twinRemovedTitle: "移除孪晶设置",
  twinUnchanged: "孪晶设置未改变",
  twinSetTitle: (n: number) => `设置孪晶：${n} 组分`,
  twinRefineWarn: "孪晶激活期间 smtbx refine 不可用，精修走 run_shelxl",
  setAdpRunning: "正在转换原子 ADP…",
  adpUnchanged: "ADP 表示未改变",
  adpTitle: (anisotropic: boolean, n: number) => `${anisotropic ? "各向异性" : "各向同性"} ADP：${n} 个原子`,
  keepsAfixTwin: "保留 AFIX 与孪晶",
  setAfixRunning: "正在更新刚体约束…",
  setAfixTitle: (n: number) => `刚体约束：${n} 组`,
  setOccRunning: "正在设置单点占有率…",
  setOccTitle: (atom: string, free: boolean) => `${atom}：${free ? "自由占有率" : "固定占有率"}`,
  setOccChip: (free: boolean, v: string) => `${free ? "初值" : "占有率"} ${v}`,
  invertRunning: "正在反转结构手性…",
  invertTitle: (op: string, sg: string) => `反转手性：${op} → ${sg}`,
  groupChangedEnantiomorph: "空间群已变（对映体对）",

  // evidence
  guestRunning: "正在做客体三项检验…",
  guestTitle: (supports: number, against: number, open: number) =>
    `客体证据：支持 ${supports} · 反对/警示 ${against}${open > 0 ? ` · 未定 ${open}` : ""}`,
  workingOccupancy: (v: string) => `工作占有率 ${v}`,
  modelElectrons: (v: string) => `模型 ${v}e`,
  conditionedByPrior: "受限制/共享变量约束",

  // skills
  listSkillsRunning: "正在检索技能卡…",
  listSkillsNone: "技能检索：无匹配",
  listSkillsTitle: (n: number) => `技能检索：${n} 张卡`,
  listSkillsNearMiss: "无卡同时命中全部关键词，已给出逐词近邻建议",
  readSkillRunning: (name: string) => `正在读技能卡 ${name}…`,
  readSkillTitle: (name: string) => `读技能卡：${name}`,
  charsCount: (n: string) => `${n} 字符`,
  paginated: "已分页（需续读）",
  investigationRunning: "正在记录研究目标与未试方向…",
  investigationNoChange: "研究目标：无新内容",
  investigationTitle: (goal: string | undefined) => `研究目标已记录${goal ? `：${goal}` : ""}`,
  tierCandidateComplete: (label: string) => `候选完整 ${label}`,
  tierScientificallyEstablished: (label: string) => `科学确立 ${label}`,
  ruledOut: (n: number) => `已否决 ${n}`,
  openDirections: (n: number) => `未试方向 ${n}`,
  investigationWarn: "有未达层级但没有记录未试方向",
  saveSkillRunning: (name: string) => `正在保存技能卡 ${name}…`,
  saveSkillTitle: (updated: boolean, name: string) => `${updated ? "更新" : "新建"}技能卡：${name}`,
  deleteSkillRunning: (name: string) => `正在删除技能卡 ${name}…`,
  deleteSkillTitle: (name: string) => `删除技能卡：${name}`,
  recoverableFromGit: "可从 git 历史恢复",

  // vision
  viewStructureRunning: (state: string) => `正在渲染结构图（${state}）…`,
  viewStructureTitle: (state: string, views: string) => `看结构：${state}${views ? `（${views}）` : ""}`,
  highlighted: (labels: string) => `标记 ${labels}`,
  situationRunning: "正在汇总全局现状（数据 / 模型 / 轨迹 / 交叉证据）…",
  situationConflicts: (n: number) => `全局现状：${n} 处证据冲突`,
  situationTitle: "全局现状综述",
  listNodesRunning: "正在查看节点列表…",
  listNodesTitle: "查看节点列表",
  compareNodesRunning: "正在对比节点…",
  compareNodesTitle: (a: string | undefined, b: string | undefined) =>
    `对比节点${a !== undefined && b !== undefined ? ` ${a} ↔ ${b}` : ""}`,

  // entry point fallbacks
  toolReturnedNotOk: "工具返回 ok=false",
  refusedNoChange: "已拒绝执行，模型未改动",
  runningTool: (tool: string) => `正在运行 ${tool}…`,
};

export const en: typeof zh = {
  // shared chips and joiners
  nodeChip: (node: string) => `Node ${node}`,
  atomsCount: (n: number | string) => `${n} atoms`,
  cellChip: (abc: string) => `Cell ${abc} Å`,
  atomFallback: "atom",
  listSeparator: "; ",
  completenessPct: (v: string | number) => `Completeness ${v}%`,
  completenessValue: (v: string) => `Completeness ${v}`,
  uniqueCount: (n: string) => `${n} unique`,
  expectedElectrons: (v: string) => `expected ${v}e`,
  notTested: (n: number) => `${n} not tested`,
  notTestedBudget: (n: number) => `${n} not tested (budget)`,
  baselineChip: (node: string) => `Baseline ${node}`,
  budgetExceededWarn: "Time budget exceeded: the untested candidates are listed; call once more to finish them",
  eStatsCentro: "E statistics favour centrosymmetric",
  eStatsNonCentro: "E statistics favour non-centrosymmetric",

  // label tables
  refineModes: {
    isotropic: "isotropic",
    anisotropic: "anisotropic",
    scale_only: "scale only",
  } as Record<string, string>,
  specialties: {
    space_group: "space group",
    chemistry: "chemical modelling",
    density: "residual density",
    validation: "structure validation",
    refinement_strategy: "refinement strategy",
  } as Record<string, string>,
  confidence: {
    high: "high",
    medium: "medium",
    low: "low",
  } as Record<string, string>,
  views: {
    a: "along a",
    b: "along b",
    c: "along c",
    oblique: "oblique",
  } as Record<string, string>,
  states: {
    asu: "asymmetric unit",
    cell: "unit cell (P1 expansion)",
    supercell: "2×2×2 packing",
  } as Record<string, string>,
  tierLabels: {
    unmet: "unmet",
    met: "met",
    not_applicable: "not applicable",
  } as Record<string, string>,

  // rendered views
  viewOpenFull: "Click to open the full image",

  // refine
  refineRunning: (mode: string | undefined) => `Running least-squares refinement${mode ? ` (${mode})` : ""}…`,
  refineDone: "Refinement complete: ",
  refineWithMask: ", with solvent mask",
  residualPeak: (v: string) => `Residual ${v} eÅ⁻³`,

  // run_shelxl
  shelxlRefineRunning: "Running SHELXL refinement…",
  shelxlCrossRunning: "Running SHELXL cross-validation…",
  disorderRevoke: (n: number) => `Disorder: ${n} groups to revoke`,
  disorderUndecided: (n: number) => `Disorder: ${n} groups undecided`,
  disorderMeasurable: (n: number) => `Disorder: ${n} groups with measurable ratio`,
  siteOccupancy: (atom: string, value: string, su: string | undefined) =>
    `${atom} occupancy ${value}${su === undefined ? " (s.u. undetermined)" : ` ± ${su}`}`,
  shelxlRefine: "SHELXL refinement",
  shelxlCross: "SHELXL cross-validation",
  metricsMissing: "metric summary not retained",
  shelxlDelta: (d: string, agrees: boolean) => ` (Δ ${d}, ${agrees ? "agrees" : "diverges"})`,
  shelxlTitle: (label: string, r1: string, delta: string) => `${label}: ${r1}${delta}`,
  shelxlNoSummary: "This record has no complete refinement summary; expand the raw result, or look at the metrics of that refinement node.",

  // fit_fragment / add_atoms_from_difference_map / edit_atoms / add_hydrogens
  fitFragmentRunning: "Fitting atoms to the ligand template…",
  fitFragmentTitle: (n: number) => `${n} atoms added from the ligand template`,
  fitFragmentRefused: (n: number) => `${n} refused (not supported by the density)`,
  addFromMapRunning: "Picking peaks from the difference map to add atoms…",
  addFromMapTitle: (n: number) => `${n} atoms added from the difference map`,
  editAtomsRunning: "Editing the model…",
  editAtomsTitle: (n: number) => `Model edited (${n} operations)`,
  addHRunning: "Adding riding hydrogens…",
  addHTitle: (n: number, elements: string[]) =>
    `${n} riding hydrogens added${elements.length > 0 ? ` (${elements.join(", ")})` : ""}`,
  carriers: (n: number) => `${n} carriers`,

  // optimize_weights / solvent_mask
  optimizeWeightsRunning: "Optimising the weighting scheme…",
  weightsOptimized: "Weights optimised: ",
  solventMaskRunning: "Computing the solvent mask…",
  solventMaskTitle: (n: number, electrons: number | undefined) =>
    `Solvent mask: ${n} voids${electrons !== undefined ? ` · ~${electrons} e⁻` : ""}`,
  solventVolume: (pct: string) => `Solvent volume ${pct}%`,

  // search_fragment_pose / accept_fragment_pose
  searchPoseRunning: "Searching whole-fragment poses…",
  searchPoseTitle: (n: number, formula: string | undefined) => {
    const tail = formula ? ` (${formula})` : "";
    return n === 0 ? `Fragment pose search: no candidates${tail}` : `Fragment pose search: ${n} candidates${tail}`;
  },
  searchPoseTop: (id: string, direct: number, weak: number, geo: number) =>
    `Best ${id} · direct peaks ${direct} · weak density ${weak} · geometry only ${geo}`,
  searchPoseFolded: (n: number) => `Symmetry-folded → ${n} independent atoms`,
  searchPoseGeoOnly: (n: number) => `${n} atoms are supported by geometry only, not by the density`,
  acceptPoseRunning: "Adding the candidate fragment to the model…",
  acceptPoseTitle: (id: string, n: number) => `Fragment candidate ${id} accepted: ${n} atoms added`,
  occupancyChip: (v: string) => `Occupancy ${v}`,

  // set_restraints / preflight_restraints
  setRestraintsRunning: "Updating restraints…",
  setRestraintsTitle: (action: string, n: number) => `Restraints ${action}: ${n} in place`,
  restraintsCrossPart: (n: number) => `${n} span non-zero PARTs; SHELXL will not apply them`,
  preflightRunning: "Pre-checking restraints…",
  preflightCount: (n: number) => `${n} restraints`,
  preflightCrossPart: (n: number) => `${n} across PARTs`,
  preflightNotRepresentable: (n: number) => `${n} not representable`,
  preflightWarnings: (n: number) => `${n} warnings`,
  preflightTitle: (parts: string) => `Restraint pre-check: ${parts}`,
  preflightCrossPartWarn: (n: number) => `SHELXL does not apply distance/plane restraints across non-zero PARTs (${n})`,

  // branch / checkout
  branchRunning: "Creating a branch…",
  branchTitle: (branch: string, at: string) => `Branch ${branch} created (from ${at})`,
  checkoutRunning: "Checking out a node…",
  checkoutTitle: (node: string, branch: string | undefined) =>
    `Checked out ${node}${branch !== undefined ? ` (${branch})` : ""}`,

  // checkCIF
  iucrRunning: "Submitting to the official IUCr checkCIF…",
  iucrPrefix: "Official IUCr checkCIF",
  checkcifCounts: (prefix: string, a: number, b: number, c: number) =>
    `${prefix}: A×${a} · B×${b} · C×${c}`,
  checkcifSalvaged: (prefix: string, parts: string | null) => `${prefix}: ${parts ?? "complete"}`,
  checkcifTruncated: "The result tail was truncated and only some alerts were recovered; see the Validation tab on the right for the full list",
  checkcifUnparsed: (prefix: string) => `${prefix} complete (result not parseable; see the Validation tab)`,

  // consult_specialist
  consultRunning: (specialty: string) => `Consulting the ${specialty ? `${specialty} ` : ""}specialist…`,
  toolCalls: (n: number) => `${n} tool calls`,
  consultTitle: (specialty: string) => `Specialist consultation (${specialty}) complete`,
  confidenceChip: (label: string) => `Confidence ${label}`,
  recommendationLabel: "Recommendation: ",
  evidenceLabel: "Evidence: ",
  risksLabel: "Risks: ",

  // check_symmetry
  checkSymmetryRunning: "Auditing space-group symmetry…",
  checkSymmetryDone: "Symmetry audit complete",
  currentSg: (sg: string) => `Current ${sg}`,
  suggestedSg: (sg: string) => `Suggested ${sg}`,
  metricPseudoSymmetry: "Lattice has metric pseudo-symmetry",
  extraSymmetryWarn: "The model obeys additional symmetry operations; re-refine in the higher-symmetry group to verify, and disclose this honestly",

  // rename_atoms
  renameRunning: "Normalising atom labels…",
  renameNoChange: "Atom labels already normalised; nothing to rename",
  renameTitle: (n: number) => `${n} atoms relabelled`,

  // import_cif_model
  importCifRunning: "Importing an external CIF structure…",
  importCifTitle: (atoms: number | string, sg: string) => `External structure imported: ${atoms} atoms, space group ${sg}`,
  anisoCount: (n: number) => `Anisotropic ${n}`,
  conversionNotes: (n: number) => `${n} conversion notes (expand the technical details to read them)`,

  // raw frames pipeline (DIALS)
  importFramesRunning: "Importing diffraction frames…",
  importFramesTitle: (n: number | string, sweeps: number | undefined) =>
    `Diffraction frames imported: ${n} images${sweeps !== undefined ? ` (${sweeps} sweeps)` : ""}`,
  backgroundFrames: (n: number) => `Background ${n}`,
  findSpotsRunning: "Finding diffraction spots…",
  findSpotsTitle: (n: string) => `Spot finding: ${n} strong spots`,
  indexRunning: "Indexing…",
  indexTitle: (n: string, pct: number | undefined) =>
    `Indexing: ${n} reflections${pct !== undefined ? ` (${pct}%)` : ""}`,
  indexLowWarn: "Indexing rate is low; the unit cell or orientation may be wrong",
  integrateRunning: "Integrating intensities…",
  integrateTitle: (n: string) => `Integration: ${n} reflections`,
  scaleRunning: "Scaling and exporting…",
  scaleTitle: (parts: string | null) => `Scale and export${parts ? `: ${parts}` : " complete"}`,
  resolutionChip: (d: number) => `Resolution ${d} Å`,
  uniqueReflections: (n: string) => `Unique reflections ${n}`,
  suggestedSpaceGroup: (sg: string) => `Suggested space group ${sg}`,
  startModelRunning: "Building the starting model…",
  startModelTitle: (n: number | string, r1: string) => `Starting model: ${n} atoms (rough-solution R1 ${r1})`,

  // finalize_delivery
  finalizeRunning: "Sealing the delivery…",
  deliveryDiagnosticSealed: "Diagnostic delivery sealed",
  deliveryFinal: "Delivery finalised",
  deliveryTitle: (status: string) => `Delivery: ${status}`,
  statusUnreported: "status not reported",
  waivedCount: (n: number) => `${n} waived`,
  waivedWarn: "Items waived: the reasons are recorded in REPORT.json and must be explained one by one in the report",

  // ghost_test / element_scan / probe_site
  ghostRunning: (n: number | string) => `Running the batch ghost-atom test (${n} atoms)…`,
  ghostTitle: (n: number, real: number, ghost: number, inconclusive: number) =>
    `Ghost test: ${n} atoms, real ${real} / ghost ${ghost} / inconclusive ${inconclusive}`,
  elementScanRunning: (site: string) => `Scanning candidate elements for ${site}…`,
  siteFallback: "the site",
  elementScanTitle: (n: number, top: string, tied: string[]) =>
    `Element scan: ${n} candidates, evidence favours ${top}${tied.length > 1 ? ` (tied: ${tied.join("/")})` : ""}`,
  notReadyCount: (n: number) => `Not ready ${n}`,
  ready: "Ready",
  elementScanBlocked: (blockers: string) => `R differences are meaningless on this model: ${blockers}`,
  elementScanHint: "Elements are decided by the chemistry (coordination number, bond lengths, cluster type, absorption edge); R is only corroborating evidence",
  probeRunning: (what: string) => `Trial-building ${what} (occupancy refined freely)…`,
  candidateAtomFallback: "candidate atoms",
  probeTitle: (n: number, supported: number, notSupported: number, borderline: number) =>
    `Low-occupancy trial: ${n} candidates, supported ${supported} / not supported ${notSupported} / borderline ${borderline}`,
  probeOccupancy: (element: string, occ: string, e: string | undefined) =>
    `${element} occupancy ${occ}${e !== undefined ? ` (${e} e)` : ""}`,
  maskOffInVoid: "Mask off (site lies inside a void)",
  probeHint: "Occupancy × Z is what the data actually pin down: a low-occupancy heavy atom carries only a few electrons, so do not use the full-occupancy electron count as the yardstick",

  // write_outputs / fourier_complete
  writeOutputsRunning: "Writing the output files…",
  writeOutputsTitle: (n: number, publication: boolean) =>
    `${n} output files written${publication ? " (publication-grade CIF+fcf)" : ""}`,
  fourierRunning: "Running Fourier completion…",
  fourierTitle: (n: number) => `Fourier completion: ${n} atoms added`,

  // observe tools
  briefRunning: "Reading the project brief…",
  briefTitle: "Project brief read",
  inspectModelRunning: "Inspecting the model…",
  inspectModelTitle: (n: number | undefined) => `Model inspected${n !== undefined ? ` (${n} atoms)` : ""}`,
  suspectAtoms: (n: number) => `Suspect atoms ${n}`,
  isolatedAtoms: (n: number) => `Isolated atoms ${n}`,
  inspectMapRunning: "Inspecting the difference density…",
  inspectMapTitle: "Difference density inspected",
  checkLigandRunning: "Comparing against the ligand template…",
  checkLigandTitle: "Ligand compared",
  geometryRunning: "Generating the geometry table…",
  geometryTitle: (nb: number, na: number, esd: boolean, truncated: boolean) =>
    `Geometry table: ${nb} bonds, ${na} angles${esd ? " (with SHELXL esd)" : " (no esd)"}${truncated ? ", truncated" : ""}`,
  packingRunning: "Generating the packing / pore / interaction tables…",
  packingTitle: (nIx: number, nV: number, pi: string | undefined, cards: number) =>
    `Packing analysis: ${nIx} interaction rows · ${nV} pores${pi !== undefined ? ` · packing ${pi} %` : ""}${cards ? ` · ${cards} HTAB cards` : ""}`,
  validateRunning: "Validating the structure…",
  validateTitle: (n: number) => `Structure validation: ${n} alerts`,
  auditReflRunning: "Examining the reflection data (twin / symmetry signs)…",
  auditReflTwin: (n: number) => `Reflection data check: twin warning signs ×${n}`,
  auditReflClean: "Reflection data check: no twin or symmetry signs",
  auditReflHints: (n: number) => `Reflection data check: ${n} hints`,
  integrateDensityRunning: "Integrating the residual electron count in the region…",
  modelClaims: (v: string) => `model claims ${v}e`,
  integrateDensityTitle: (bits: string | null) => `Residual electron integration${bits ? `: ${bits}` : ""}`,
  auditElementRunning: "Auditing C/N/O element-assignment evidence…",
  auditElementTitle: (n: number, idle: number) => `Element-assignment evidence: ${n} sites need judgement (idle N/O ×${idle})`,
  auditElementClean: "Element-assignment evidence: no anomalous signals",

  // data ingest / reduction
  ingestRunning: "Ingesting vendor data…",
  ingestTitle: (hkl: string) => `Vendor data ingested: ${hkl}`,
  hklf5Domains: (n: number | string) => `HKLF5 · ${n} domains`,
  crysalisRunning: "Reducing data with CrysAlisPro (peak search / indexing / integration)…",
  crysalisTitle: (n: string) => `CrysAlisPro reduction complete: ${n} reflection rows`,
  stepsCount: (n: number) => `${n} steps`,
  estimateResRunning: "Assessing the evidence for a resolution cut-off…",
  estimateResNone: "Resolution assessment: no shell meets the criteria (weak or already merged data)",
  estimateResTitle: (d: string, cur: string | undefined) =>
    `Resolution assessment: suggested d_min ${d} Å${cur === undefined ? "" : ` (current ${cur})`}`,
  shellsCount: (n: number) => `${n} shells`,
  latticeChip: (c: string) => `Lattice ${c}`,
  exportHklf5Running: "Exporting two-domain HKLF5 data…",
  exportHklf5Title: (composites: string, clean: string) =>
    `HKLF5 exported: ${composites} composites · ${clean} clean major-domain reflections`,
  reusedIntegration: "Reused integration cache",
  swapRunning: (hkl: string) => `Switching to reflection data ${hkl}…`,
  swapTitle: (to: string, hklf: number | string, domains: number | undefined) =>
    `Data switched: ${to} (HKLF${hklf}${domains === undefined ? "" : ` · ${domains} domains`})`,
  observations: (n: string) => `${n} observations`,
  setExperimentRunning: "Recording experiment metadata…",
  setExperimentTitle: (fields: string | null) => `Experiment metadata recorded: ${fields ?? "(none)"}`,
  removedCount: (n: number) => `${n} removed`,
  removeAbsent: (keys: string) => `Requested for removal but absent: ${keys}`,

  // structure solution
  chargeFlipRunning: "Solving by charge flipping…",
  chargeFlipTitle: (corr: string, n: number | string) => `Charge flipping: map correlation ${corr} · ${n} peaks`,
  seedChip: (n: number) => `Seed ${n}`,
  superflipRunning: "Solving with Superflip…",
  superflipTitle: (r: string, n: number | string) => `Superflip: R ${r}% · ${n} peaks`,
  symmetryAgreement: (v: string) => `Symmetry agreement ${v}`,
  cyclesCount: (n: number) => `${n} cycles`,
  superflipSymWarn: "The density does not obey the assumed symmetry operators; the space group is in doubt, so check the symmetry before continuing",
  shelxtRunning: "Solving with SHELXT (dual space)…",
  shelxtAdoptedTitle: (sg: string, n: number | string) => `SHELXT solved and adopted: ${sg} · ${n} atoms`,
  shelxtTitle: (n: number) => `SHELXT solution: ${n} candidates (not adopted)`,
  bestChip: (sg: string) => `Best ${sg}`,
  interpretRunning: "Interpreting the peak list as atoms…",
  interpretTitle: (n: number | string, comp: string) => `Peaks interpreted as atoms: ${n}${comp ? ` (${comp})` : ""}`,
  symmetryGhostsRemoved: (n: number) => `Symmetry ghosts removed ${n}`,
  compositionUnknown: "Composition unknown",
  unassignedHeavyWarn: (n: number) => `${n} probable heavy-atom sites unassigned; the element assignment may be wrong`,

  // symmetry
  screenSgRunning: "Screening candidate space groups…",
  screenSgTitle: (sg: string, n: number, total: number | string) => `Space-group screen: best ${sg} (${n}/${total} candidates)`,
  violationRate: (v: string) => `Violation rate ${v}%`,
  auditHeavyRunning: "Auditing heavy-atom sites…",
  auditHeavyTitle: (n: number | string, ready: boolean) =>
    `Heavy-site audit: ${n} sites, R-vs-Z ${ready ? "feasible" : "not ready"}`,
  absorptionEdges: (edges: string) => `Absorption edges: ${edges}`,
  blockersCount: (n: number) => `Blockers ${n}`,
  reflStatsRunning: "Computing reflection statistics…",
  reflStatsTitle: (laue: string, n: string) => `Reflection statistics: Laue class ${laue}, ${n} unique`,
  fileCentring: (c: string) => `File carries ${c} centring`,
  laueScan: (n: number) => `Laue scan ${n} classes`,
  changeSgRunning: (sg: string) => `Changing space group to ${sg}…`,
  declareSgTitle: (sg: string) => `Space group declared: ${sg}`,
  changeSgTitle: (from: string, to: string) => `Space group changed: ${from} → ${to}`,
  atomsDelta: (from: number, to: number) => `Atoms ${from} → ${to}`,
  opsVerified: (n: number) => `${n} added operators verified`,
  hStripped: (n: number) => `${n} H stripped`,
  droppedState: (items: string) => `Session state lost: ${items} (must be rebuilt)`,
  ncsRunning: "Auditing pseudo-symmetry (translation / inversion hypotheses)…",
  ncsTitle: (inversion: boolean, pct: string) => `Pseudo-symmetry audit: ${inversion ? "inversion" : "translation"} hypothesis matches ${pct}%`,
  ncsTitlePlain: "Pseudo-symmetry audit",
  rationalOperator: "Operator falls on rational fractions",
  ncsWarn: "Strong match + rational operator = crystallographic symmetry may have been missed; check the symmetry and question the unit cell first",
  assembleRunning: "Assembling a coherent asymmetric unit…",
  asuCoherent: (n: number | string) => `ASU already coherent (${n} fragments)`,
  asuDryRun: (steps: number, before: number | string) => `ASU assembly dry run: ${steps} steps (${before} detached atoms)`,
  asuAssembled: (steps: number, before: number | string, after: number | string) =>
    `ASU assembled: ${steps} steps, detached atoms ${before} → ${after}`,
  occupancyRescaled: (n: number) => `Occupancy rescaled ${n}`,
  ghostSuspects: (n: number, labels: string) => `${n} ghost-atom suspects remain: ${labels}`,

  // refinement / twin state
  olex2Running: "Cross-checking independently with olex2.refine…",
  olex2Title: (r1: string) => `olex2 independent check: R1 ${r1}`,
  deltaVsSession: (d: string) => `Δ vs this session ${d}`,
  setWeightsRunning: "Setting the weighting scheme…",
  setWeightsTitle: (from: string, to: string) => `Weights set, WGHT: ${from} → ${to}`,
  removeResRunning: "Removing the resolution cut-off…",
  setResRunning: (d: string | number) => `Setting the resolution cut-off d_min ${d}…`,
  removeResTitle: "Resolution cut-off removed (full resolution restored)",
  setResTitle: (shel: string) => `Resolution cut-off: ${shel}`,
  setZRunning: "Setting Z…",
  setZTitle: (from: number | string, to: number | string, zPrime: string) =>
    `Z set: ${from} → ${to} (Z' ${zPrime})`,
  groupOrder: (n: number) => `Group order ${n}`,
  undoDisorderRunning: (undo: string) => `Undoing the disorder split (${undo})…`,
  splitDisorderRunning: (atoms: string) => `Splitting disordered sites${atoms ? ` (${atoms})` : ""}…`,
  undoDisorderTitle: (undone: string, n: number) => `Disorder split ${undone} undone: ${n} pairs merged back to single sites`,
  deletedAtoms: (labels: string) => `Deleted ${labels}`,
  fvarRenumbered: "FVAR renumbered",
  restraintsPruned: (n: number) => `${n} restraints pointing at deleted atoms were also pruned`,
  splitDisorderTitle: (n: number) => `Disorder split: ${n} sites (PART 1/2; the ratio awaits SHELXL refinement)`,
  occupancyAStart: (v: string) => `A occupancy ${v} (starting value)`,
  restraintSuggestion: "SADI/SIMU suggestion attached",
  bSitesFolded: (n: number) => `${n} B sites folded into the cell by symmetry`,
  twinSuggestRunning: "Listing possible twin laws…",
  twinRemoveRunning: "Removing the twin setting…",
  twinSetRunning: "Setting the twin law…",
  twinCandidatesTitle: (n: number) => `Twin-law candidates: ${n} (not applied)`,
  listOnly: "List only",
  twinRemovedTitle: "Twin setting removed",
  twinUnchanged: "Twin setting unchanged",
  twinSetTitle: (n: number) => `Twin set: ${n} components`,
  twinRefineWarn: "While the twin is active smtbx refine is unavailable; refine through run_shelxl",
  setAdpRunning: "Converting atom ADPs…",
  adpUnchanged: "ADP representation unchanged",
  adpTitle: (anisotropic: boolean, n: number) => `${anisotropic ? "Anisotropic" : "Isotropic"} ADP: ${n} atoms`,
  keepsAfixTwin: "AFIX and twin preserved",
  setAfixRunning: "Updating rigid-group constraints…",
  setAfixTitle: (n: number) => `Rigid-group constraints: ${n} groups`,
  setOccRunning: "Setting a single-site occupancy…",
  setOccTitle: (atom: string, free: boolean) => `${atom}: ${free ? "free occupancy" : "fixed occupancy"}`,
  setOccChip: (free: boolean, v: string) => `${free ? "Start value" : "Occupancy"} ${v}`,
  invertRunning: "Inverting the structure's chirality…",
  invertTitle: (op: string, sg: string) => `Chirality inverted: ${op} → ${sg}`,
  groupChangedEnantiomorph: "Space group changed (enantiomorphic pair)",

  // evidence
  guestRunning: "Running the three guest checks…",
  guestTitle: (supports: number, against: number, open: number) =>
    `Guest evidence: supports ${supports} · against/warns ${against}${open > 0 ? ` · undecided ${open}` : ""}`,
  workingOccupancy: (v: string) => `Working occupancy ${v}`,
  modelElectrons: (v: string) => `model ${v}e`,
  conditionedByPrior: "Conditioned by restraints / shared variables",

  // skills
  listSkillsRunning: "Searching skill cards…",
  listSkillsNone: "Skill search: no match",
  listSkillsTitle: (n: number) => `Skill search: ${n} cards`,
  listSkillsNearMiss: "No card matches every keyword; per-word near matches are suggested",
  readSkillRunning: (name: string) => `Reading skill card ${name}…`,
  readSkillTitle: (name: string) => `Skill card read: ${name}`,
  charsCount: (n: string) => `${n} characters`,
  paginated: "Paginated (continue reading)",
  investigationRunning: "Recording the research goal and untried directions…",
  investigationNoChange: "Research goal: nothing new",
  investigationTitle: (goal: string | undefined) => `Research goal recorded${goal ? `: ${goal}` : ""}`,
  tierCandidateComplete: (label: string) => `Candidate complete: ${label}`,
  tierScientificallyEstablished: (label: string) => `Scientifically established: ${label}`,
  ruledOut: (n: number) => `Ruled out ${n}`,
  openDirections: (n: number) => `Untried directions ${n}`,
  investigationWarn: "Some tiers are unmet but no untried directions were recorded",
  saveSkillRunning: (name: string) => `Saving skill card ${name}…`,
  saveSkillTitle: (updated: boolean, name: string) => `Skill card ${updated ? "updated" : "created"}: ${name}`,
  deleteSkillRunning: (name: string) => `Deleting skill card ${name}…`,
  deleteSkillTitle: (name: string) => `Skill card deleted: ${name}`,
  recoverableFromGit: "Recoverable from git history",

  // vision
  viewStructureRunning: (state: string) => `Rendering the structure view (${state})…`,
  viewStructureTitle: (state: string, views: string) => `Structure view: ${state}${views ? ` (${views})` : ""}`,
  highlighted: (labels: string) => `Highlighted ${labels}`,
  situationRunning: "Summarising the overall situation (data / model / trajectory / cross-evidence)…",
  situationConflicts: (n: number) => `Overall situation: ${n} evidence conflicts`,
  situationTitle: "Overall situation report",
  listNodesRunning: "Listing nodes…",
  listNodesTitle: "Node list viewed",
  compareNodesRunning: "Comparing nodes…",
  compareNodesTitle: (a: string | undefined, b: string | undefined) =>
    `Nodes compared${a !== undefined && b !== undefined ? ` ${a} ↔ ${b}` : ""}`,

  // entry point fallbacks
  toolReturnedNotOk: "Tool returned ok=false",
  refusedNoChange: "Refused to run; model unchanged",
  runningTool: (tool: string) => `Running ${tool}…`,
};
