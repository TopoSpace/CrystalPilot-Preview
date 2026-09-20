/** Strings for the crystal pane components under workbench/crystal/.
 *  `en` is typed against `zh`: both must carry the same keys. */

export const zh = {
  // shared by several crystal components
  loadingNode: (node: string | null) => `正在加载 ${node}`,
  cannotLoadNode: (node: string | null) => `无法加载 ${node}`,
  viewNodeAria: (id: string) => `查看节点 ${id}`,
  locateAria: (label: string) => `定位 ${label}`,
  perCell: "每胞",
  listSeparator: "、",
  colon: "：",

  // StructureComparison
  cmpFieldNames: {
    data_revision: "反射数据", data_binding: "数据来源", engine: "精修引擎",
    weights: "权重", weighting: "权重", wght: "权重", h: "氢处理", hydrogen: "氢处理",
    mask: "掩膜", twin: "孪晶", cutoff: "反射范围", shel: "SHEL", omit: "OMIT",
    hklf: "HKLF", scale: "数据尺度", scale_k: "拟合尺度", cell: "晶胞",
    space_group: "空间群", wavelength: "波长", metrics_source: "指标来源",
    "cutoff.selected_reflections": "精修反射数", "cutoff.applied": "实际反射范围",
    "cutoff.requested": "请求反射范围", metric_definition: "指标定义", hydrogens: "氢处理",
  } as Record<string, string>,
  cmpNotRecorded: "未记录",
  cmpUnknown: "未知",
  cmpNotFullyRecorded: "未完整记录",
  cmpRevision: "修订",
  cmpStructureOnly: "仅结构",
  cmpData: (revision: string) => `数据 ${revision}`,
  cmpLegacyUnbound: "历史数据未绑定",
  cmpEngineNotRecorded: "引擎未记录",
  cmpMetricSourceIncomplete: "指标来源未完整记录",
  cmpInheritedNote: "沿用指标，非本节点精修",
  cmpRefinedReflections: "精修反射",
  cmpCutoff: "反射范围",
  cmpCutoffIgnored: "请求指令未应用",
  cmpCutoffUnknown: "应用情况未明",
  cmpCutoffNone: "无附加范围指令",
  cmpQuoteNode: (id: string, metrics: string, nAtoms: number, dataRevision: string, metricsNode: string, inherited: boolean) =>
    `${id}：${metrics}；模型 ASU ${nAtoms} 原子；数据 ${dataRevision}；指标来源 ${metricsNode}${inherited ? "（沿用）" : ""}`,
  cmpQuoteMetric: (label: string, status: string) => `${label}：${status}`,
  cmpQuote: (baseline: string, node: string, metrics: string[], frameNote: string) =>
    `${baseline}\n${node}\n${metrics.join("；")}。${frameNote}。仅查看比较，未检出节点。`,
  cmpFrameCompatibleQuote: "坐标系可共用镜头，但跨节点原子身份未确认",
  cmpFrameCompatible: "相机同步 · 选择独立",
  cmpFrameDifferent: "坐标系不同，分别查看",
  cmpFrameUnknown: "坐标系未确认，分别查看",
  cmpGroupAria: "比较结构",
  cmpViewAria: (baseline: boolean, id: string) => `查看${baseline ? "基线" : "对比"} ${id}`,
  cmpBefore: "前",
  cmpAfter: "后",
  cmpBaseline: "基线",
  cmpView: "查看",
  cmpQuoteBtn: "引用对比",
  cmpExitBtn: "退出对比",
  cmpTableAria: "节点数值对比",
  cmpMetricCol: "指标",
  cmpChangeCol: "变化",
  cmpChangeTip: "查看节点减基线；条件未明或不同时仅显示中性数值",
  cmpInheritedSuffix: " · 含沿用指标",
  cmpModelAsu: "模型 ASU",
  cmpDrawnTip: "绘制数不含已隐藏元素/PART及分数剖面外原子；相机遮挡不改变计数",
  cmpDrawnLine: (node: string, drawn: number, total: number, truncated: boolean) =>
    `${node} · 绘制 ${drawn} / 场景 ${total} 原子${truncated ? "（已截断）" : ""}`,
  cmpSceneFailed: "结构加载失败",
  cmpConditionsUnavailable: "暂无法核对条件，仍可查看结构",
  cmpSymops: (n: number | string) => `${n} 个空间群操作`,
  cmpFactsAria: "其它节点事实",
  cmpDiffLine: (field: string, from: string, to: string) => `${field}：${from} → ${to}`,
  cmpUnrecordedPrefix: "未记录：",
  cmpLegacyNote: "历史数据未绑定；不使用当前反射替算。",
  cmpRequestVerify: (baseline: string, node: string) =>
    `请核对节点 ${baseline} 与 ${node} 的历史反射数据来源及逐指标比较条件。无法确认的绑定保持未知，不要把当前 HKL 自动绑定到历史节点；请先说明可验证的来源和需要我确认的内容。`,
  cmpRequestVerifyBtn: "请求核对来源",

  // AnalysisInspector
  inspAtomLocated: "已定位当前显示原子；配位数来自本次显示的成键列表。",
  inspSceneError: "显示范围加载失败；未把分析行绑定到旧场景。",
  inspWaiting: "正在载入相互作用显示实例…",
  inspLayerOff: "该关系图层已关闭；再次选择表格行可重新显示。",
  inspNoMatch: "当前范围未找到该实例（可能在范围外或被预算截断）；未替选 ASU 原子。可在结构范围菜单中调整。",
  inspCentroidOnly: "已显示质心连线；数据未提供端点原子映射，未猜选环原子。",
  inspBoundary: "已定位范围内端点；另一端在显示范围外。",
  inspLocated: "已定位实际端点；分析表按对称独立关系计数，不随超胞复制。",
  inspClearAria: "清除检查选择",
  inspHiddenEndpoint: "端点元素或 PART 已隐藏，关系线不可见；定位标记仍使用实际原子坐标。",
  inspSourceSummary: "显示实例与来源",
  inspFrom: "起点",
  inspTo: "终点",
  inspInstanceCount: (n: number | undefined) => `${n} 条显示实例（非每胞数量）`,
  inspKindTruncated: "此类显示关系已被预算截断",
  inspHaloShort: "边界搜索范围不足",

  // CrystalToolbar
  tbReflectionsUnconfirmed: "该节点反射来源未确认",
  tbReflectionsUnconfirmedNote: "反射来源未确认；仍可查看结构",
  tbCompareParent: "与父节点对比",
  tbCamera: "相机",
  tbCameraTip: "相机远雾与前后裁切；不改变晶体或分数剖面",
  tbFog: "远雾",
  tbFogTip: "仅淡化远处显示，不是景深",
  tbReset: "重置",
  tbClip: (pct: number) => `前后 ${pct}%`,
  tbClipAria: "前后裁切",
  tbClipTip: "100% 显示全部原子；降低后从镜头前后对称裁切",
  tbFogStart: (pct: number) => `雾起 ${pct}%`,
  tbFogStartAria: "远雾起点",

  // CrystalPane
  paneSymmetryCopy: "对称拷贝",
  paneFrameFile: (node: string, stamp: string) => `视图-${node}-${stamp}.png`,
  paneSymmetryCoverage: (drawn: number, requested: number) => `对称 ${drawn}/${requested} 胞`,
  panePeaksCoverage: (drawn: number, requested: number) => `Q峰 ${drawn}/${requested} 点`,
  paneVoidsPerCell: (n: number) => `每胞 ${n} 孔`,
  paneLayerLimitTip: "请求范围 / 实际绘制；各层资源限额独立",
  paneCollapseStructure: "收起结构",
  paneShowStructure: "显示结构",
  paneStructureShareAria: "结构显示比例",
  paneStructureShareValue: (pct: number) => `结构 ${pct}%`,

  // CrystalViewer
  viewerCavity: "腔",

  // AnalysisPanel
  anMissingRingList: (rings: { key: string; op: string; size: number }[]) =>
    rings.map((r) => `${r.key} × ${r.op}（${r.size} 元）`).join("；"),
  anCoverageIncomplete: "关系覆盖不完整",
  anHSourceUnknown: "氢原子来源未知",
  anStraddles: "跨区域",
  anTruncatedParen: "（截断）",
  anCurrentCoordination: "当前显示配位",
  anSectionsSummary: (hidden: string[]) => `显示区块${hidden.length > 0 ? ` · 已折叠 ${hidden.join("、")}` : ""}`,

  // StructureHeader
  hdrComparable: "条件可比",
  hdrNotComparable: "条件未明或不同，仅显示数值变化",
  hdrDataToParams: (ratio: string) => `数据/参数 ${ratio}`,
  hdrDrawn: "绘制",
  hdrBonds: (n: number) => `${n} 键`,
  hdrPolyhedra: (n: number) => `${n} 多面体`,
  hdrAsuNotInExtent: "完整 ASU 组成未包含在当前显示范围中",
  hdrAsuAtoms: (n: number) => `${n} ASU 原子`,

  // CoordinationSection
  coordUnavailable: "当前节点的显示成键列表尚不可用",
  coordDisplayOnly: "仅当前显示成键，不是完整晶体的配位结论。",
  coordTruncated: "显示原子被截断，配位数可能不完整。",
  coordLocateAria: (label: string) => `定位配位原子 ${label}`,
  coordSymImage: " · 对称像",
  coordEtaTip: (n: number) => `${n} 个 η 配体（环整体计一个配位位点）`,
  coordMetalContactsTip: (n: number) => `${n} 个金属–金属接触（簇内），未计入 CN`,

  // MetricsPanel
  mtSparklineAria: "节点数值记录；仅连接已核对的最后一对",
  mtToolCol: "工具",

  // ValidationPanel
  valTimeoutPrefix: "检查超时 · ",
  valCancelledPrefix: "检查已取消 · ",

  // extent.ts
  extGrowLayers: (n: number) => `${n} 层`,
  extManual: (n: number) => `手工 ${n} 处`,
  extWithExtras: (slice: string, extras: string[]) => `${slice}（${extras.join("，")}）`,
};

export const en: typeof zh = {
  // shared by several crystal components
  loadingNode: (node: string | null) => `Loading ${node}`,
  cannotLoadNode: (node: string | null) => `Cannot load ${node}`,
  viewNodeAria: (id: string) => `View node ${id}`,
  locateAria: (label: string) => `Locate ${label}`,
  perCell: "per cell",
  listSeparator: ", ",
  colon: ": ",

  // StructureComparison
  cmpFieldNames: {
    data_revision: "reflection data", data_binding: "data source", engine: "refinement engine",
    weights: "weighting scheme", weighting: "weighting scheme", wght: "weighting scheme", h: "hydrogen treatment", hydrogen: "hydrogen treatment",
    mask: "solvent mask", twin: "twin", cutoff: "reflection range", shel: "SHEL", omit: "OMIT",
    hklf: "HKLF", scale: "data scale", scale_k: "fitted scale", cell: "unit cell",
    space_group: "space group", wavelength: "wavelength", metrics_source: "metric source",
    "cutoff.selected_reflections": "reflections refined", "cutoff.applied": "applied reflection range",
    "cutoff.requested": "requested reflection range", metric_definition: "metric definition", hydrogens: "hydrogen treatment",
  } as Record<string, string>,
  cmpNotRecorded: "not recorded",
  cmpUnknown: "unknown",
  cmpNotFullyRecorded: "not fully recorded",
  cmpRevision: "revision",
  cmpStructureOnly: "structure only",
  cmpData: (revision: string) => `Data ${revision}`,
  cmpLegacyUnbound: "Historical data not bound",
  cmpEngineNotRecorded: "engine not recorded",
  cmpMetricSourceIncomplete: "Metric source not fully recorded",
  cmpInheritedNote: "Inherited metrics, not refined at this node",
  cmpRefinedReflections: "Reflections refined",
  cmpCutoff: "Reflection range",
  cmpCutoffIgnored: "requested instruction not applied",
  cmpCutoffUnknown: "application unknown",
  cmpCutoffNone: "no additional range instruction",
  cmpQuoteNode: (id: string, metrics: string, nAtoms: number, dataRevision: string, metricsNode: string, inherited: boolean) =>
    `${id}: ${metrics}; model ASU ${nAtoms} atoms; data ${dataRevision}; metric source ${metricsNode}${inherited ? " (inherited)" : ""}`,
  cmpQuoteMetric: (label: string, status: string) => `${label}: ${status}`,
  cmpQuote: (baseline: string, node: string, metrics: string[], frameNote: string) =>
    `${baseline}\n${node}\n${metrics.join("; ")}. ${frameNote}. Comparison view only; no node checked out.`,
  cmpFrameCompatibleQuote: "the coordinate frames can share a camera, but atom identity across nodes is unconfirmed",
  cmpFrameCompatible: "camera synchronised · selection independent",
  cmpFrameDifferent: "coordinate frames differ; view separately",
  cmpFrameUnknown: "coordinate frames unconfirmed; view separately",
  cmpGroupAria: "Compare structures",
  cmpViewAria: (baseline: boolean, id: string) => `View ${baseline ? "baseline" : "comparison"} ${id}`,
  cmpBefore: "Before",
  cmpAfter: "After",
  cmpBaseline: "Baseline",
  cmpView: "View",
  cmpQuoteBtn: "Quote comparison",
  cmpExitBtn: "Exit comparison",
  cmpTableAria: "Node metric comparison",
  cmpMetricCol: "Metric",
  cmpChangeCol: "Change",
  cmpChangeTip: "Viewed node minus baseline; when conditions are unknown or differ, only a neutral value is shown",
  cmpInheritedSuffix: " · includes inherited metrics",
  cmpModelAsu: "Model ASU",
  cmpDrawnTip: "The drawn count excludes hidden elements/PARTs and atoms outside the fractional slab; camera occlusion does not change it",
  cmpDrawnLine: (node: string, drawn: number, total: number, truncated: boolean) =>
    `${node} · drawn ${drawn} / scene ${total} atoms${truncated ? " (truncated)" : ""}`,
  cmpSceneFailed: "Structure failed to load",
  cmpConditionsUnavailable: "Conditions cannot be checked right now; the structures can still be viewed",
  cmpSymops: (n: number | string) => `${n} space-group operations`,
  cmpFactsAria: "Other node facts",
  cmpDiffLine: (field: string, from: string, to: string) => `${field}: ${from} → ${to}`,
  cmpUnrecordedPrefix: "Not recorded: ",
  cmpLegacyNote: "Historical data not bound; the current reflections are not substituted for it.",
  cmpRequestVerify: (baseline: string, node: string) =>
    `Please verify the historical reflection-data sources of nodes ${baseline} and ${node} and the comparison conditions metric by metric. Leave any binding that cannot be confirmed as unknown and do not bind the current HKL to historical nodes automatically; first state the verifiable sources and what you need me to confirm.`,
  cmpRequestVerifyBtn: "Request source check",

  // AnalysisInspector
  inspAtomLocated: "Located the currently displayed atom; the coordination number comes from the bond list of this display.",
  inspSceneError: "The displayed extent failed to load; the analysis row was not bound to the old scene.",
  inspWaiting: "Loading the displayed interaction instance…",
  inspLayerOff: "That interaction layer is switched off; select the table row again to show it.",
  inspNoMatch: "This instance was not found in the current extent (it may lie outside it or have been cut by the budget); no ASU atom was substituted. Adjust the extent in the structure extent menu.",
  inspCentroidOnly: "Showing the centroid line; the data gives no endpoint atom mapping, so no ring atoms were guessed.",
  inspBoundary: "Located the endpoint inside the extent; the other end lies outside the displayed extent.",
  inspLocated: "Located the actual endpoints; the analysis table counts symmetry-independent interactions and does not multiply them with the supercell.",
  inspClearAria: "Clear inspection selection",
  inspHiddenEndpoint: "An endpoint element or PART is hidden, so the interaction line is not visible; the locator still uses the actual atom coordinates.",
  inspSourceSummary: "Displayed instance and source",
  inspFrom: "from",
  inspTo: "to",
  inspInstanceCount: (n: number | undefined) => `${n} displayed instances (not a per-cell count)`,
  inspKindTruncated: "Displayed interactions of this kind were cut by the budget",
  inspHaloShort: "Boundary search range insufficient",

  // CrystalToolbar
  tbReflectionsUnconfirmed: "Reflection source for this node unconfirmed",
  tbReflectionsUnconfirmedNote: "Reflection source unconfirmed; the structure can still be viewed",
  tbCompareParent: "Compare with parent",
  tbCamera: "Camera",
  tbCameraTip: "Camera fog and depth clipping; does not change the crystal or the fractional slab",
  tbFog: "Fog",
  tbFogTip: "Only fades distant parts of the view; not depth of field",
  tbReset: "Reset",
  tbClip: (pct: number) => `Depth ${pct}%`,
  tbClipAria: "Depth clipping",
  tbClipTip: "100% shows every atom; lower values clip symmetrically in front of and behind the camera target",
  tbFogStart: (pct: number) => `Fog from ${pct}%`,
  tbFogStartAria: "Fog start",

  // CrystalPane
  paneSymmetryCopy: "symmetry copy",
  paneFrameFile: (node: string, stamp: string) => `view-${node}-${stamp}.png`,
  paneSymmetryCoverage: (drawn: number, requested: number) => `Symmetry ${drawn}/${requested} cells`,
  panePeaksCoverage: (drawn: number, requested: number) => `Q peaks ${drawn}/${requested} points`,
  paneVoidsPerCell: (n: number) => `${n} voids per cell`,
  paneLayerLimitTip: "Requested extent / actually drawn; each layer has its own resource budget",
  paneCollapseStructure: "Hide structure",
  paneShowStructure: "Show structure",
  paneStructureShareAria: "Structure view share",
  paneStructureShareValue: (pct: number) => `Structure ${pct}%`,

  // CrystalViewer
  viewerCavity: "cavity",

  // AnalysisPanel
  anMissingRingList: (rings: { key: string; op: string; size: number }[]) =>
    rings.map((r) => `${r.key} × ${r.op} (${r.size}-membered)`).join("; "),
  anCoverageIncomplete: "Interaction coverage incomplete",
  anHSourceUnknown: "Hydrogen atom source unknown",
  anStraddles: "spans regions",
  anTruncatedParen: " (truncated)",
  anCurrentCoordination: "Coordination in the current display",
  anSectionsSummary: (hidden: string[]) => `Sections shown${hidden.length > 0 ? ` · folded: ${hidden.join(", ")}` : ""}`,

  // StructureHeader
  hdrComparable: "conditions comparable",
  hdrNotComparable: "conditions unknown or different; only the numeric change is shown",
  hdrDataToParams: (ratio: string) => `Data/parameters ${ratio}`,
  hdrDrawn: "drawn",
  hdrBonds: (n: number) => `${n} bonds`,
  hdrPolyhedra: (n: number) => `${n} polyhedra`,
  hdrAsuNotInExtent: "The full ASU composition is not within the current displayed extent",
  hdrAsuAtoms: (n: number) => `${n} ASU atoms`,

  // CoordinationSection
  coordUnavailable: "The bond list for the current node's display is not yet available",
  coordDisplayOnly: "Bonds in the current display only; not a coordination conclusion for the whole crystal.",
  coordTruncated: "Displayed atoms are truncated; coordination numbers may be incomplete.",
  coordLocateAria: (label: string) => `Locate coordinating atom ${label}`,
  coordSymImage: " · symmetry image",
  coordEtaTip: (n: number) => `${n} η ligands (each ring counts as one coordination site)`,
  coordMetalContactsTip: (n: number) => `${n} metal–metal contacts (within the cluster), not counted in CN`,

  // MetricsPanel
  mtSparklineAria: "Node metric history; only the last verified pair is connected",
  mtToolCol: "Tool",

  // ValidationPanel
  valTimeoutPrefix: "Check timed out · ",
  valCancelledPrefix: "Check cancelled · ",

  // extent.ts
  extGrowLayers: (n: number) => `${n} layers`,
  extManual: (n: number) => `${n} grown by hand`,
  extWithExtras: (slice: string, extras: string[]) => `${slice} (${extras.join(", ")})`,
};
