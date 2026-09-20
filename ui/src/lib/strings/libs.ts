/** Strings for the helper modules under lib/ (quote, humanizeCommand, slash commands, stages, ...).
 *  `en` is typed against `zh`: both must carry the same keys. */

export const zh = {
  // punctuation shared by the sentence builders below
  /** enumeration separator inside a list ("a、b、c") */
  sepList: "、",
  /** clause separator between facts ("a；b") */
  sepClause: "；",
  /** comma between two facts of one clause */
  sepComma: "，",
  /** parenthetical aside appended to a phrase */
  parens: (s: string) => `（${s}）`,

  // quote.ts - atom
  quoteAtomSymCopy: (op: string) => `对称拷贝 ${op}`,
  quoteAtomAdpUnknown: "ADP 未报告",
  quoteAtomOcc: (occ: string) => `占有率 ${occ}`,
  /** facts / reasons / items / parts below arrive pre-joined with sepList or sepClause */
  quoteAtomHead: (elem: string, label: string, facts: string) =>
    `请看 ${elem} 原子 ${label}（${facts}）`,
  quoteAtomStructureOnly: (head: string) =>
    `${head}：源 CIF 中它的配位和几何环境如何？（当前只有结构，无观测反射数据）`,
  quoteAtomWithReasons: (head: string, reasons: string) =>
    `${head}：${reasons}。这是无序、错元素、还是位置本身有问题？`,
  quoteAtomDefault: (head: string) => `${head}：它周围的差值密度与配位环境如何？`,

  // quote.ts - difference-map peak
  quotePeakAt: (coords: string) => `分数坐标 (${coords})`,
  quotePeakNear: (atom: string, d: string) => `（距 ${atom} ${d} Å）`,
  quotePeak: (at: string, near: string, height: string) =>
    `请检查${at}${near}处高 ${height} eÅ⁻³ 的差值密度峰：` +
    `是缺原子、无序分量还是噪音？（先核对引用节点，再用 inspect_map 刷新峰表定位）`,

  // quote.ts - measurement
  quoteMeasure: (text: string) =>
    `我在结构里量到 ${text}（视图读数，未带 esd）：` + `这个几何合理吗？需要限制/约束吗？`,

  // quote.ts - whole structure
  quoteStructureHead: (node: string | null) => `当前模型${node ? `（节点 ${node}）` : ""}`,
  quoteSpaceGroup: (sg: string) => `空间群 ${sg}`,
  quoteCell: (lengths: string, angles: string) => `胞 ${lengths} / ${angles}`,
  quoteAtomsCount: (n: number) => `${n} 原子`,
  quoteParamsCount: (n: number) => `${n} 参数`,
  quoteRestraintsCount: (n: number) => `${n} 限制`,
  quoteResidualPeak: (v: string) => `残峰 ${v}`,
  quoteResidualHole: (v: string) => `残洞 ${v} eÅ⁻³`,
  quoteCompleteness: (pct: string) => `完整度 ${pct}%`,
  quoteUniqueCount: (n: number) => `${n} 独立衍射`,
  quoteData: (items: string) => `数据 ${items}`,
  quoteStructure: (head: string, items: string) =>
    `${head}：${items}。你怎么看现在的状态，下一步该做什么？`,

  // quote.ts - rendered frame
  quoteFrameTruncated: "显示已截断，只是结构的一部分",
  quoteFrameLayers: (layers: string) => `叠加：${layers}`,
  quoteNodeLabel: (node: string) => `节点 ${node}`,
  quoteCurrentModel: "当前模型",
  quoteFrame: (where: string, bits: string) =>
    `这是我现在在看的画面（${where}；${bits}）。` + `图里有什么值得注意的？`,

  // quote.ts - guest / counter-ion site
  quoteGuestSite: {
    cage_cavity: "笼内",
    channel: "通道中",
    cavity: "分子间空腔",
    interstitial: "晶格间隙",
  },
  quoteGuestPosition: (site: string) => `位置 ${site}`,
  quoteGuestVoid: (id: number) => `孔 V${id}`,
  quoteGuestHostFragment: (fragment: string) => `宿主片段 ${fragment}`,
  quoteGuestClearance: (d: string) => `最近间隙 ${d} Å`,
  quoteGuestContact: (atom: string, hostAtom: string, op: string | null, d: string) =>
    `最近接触 ${atom}···${hostAtom}${op ? `（${op}）` : ""} ${d} Å`,
  quoteGuestStraddles: "原子跨越两个区域",
  quoteGuest: (formula: string, fragment: string, copies: number, parts: string) =>
    `客体 ${formula}（${fragment}，${copies} 份）：${parts}：这个归属合理吗？对建模/掩膜决定有什么影响？`,

  // quote.ts - pore (voids.json v3)
  quotePoreVolume: (v: number) => `体积 ${v} Å³`,
  quotePoreDirs: (name: string, dirs: string) => `${name}（方向 ${dirs}）`,
  quotePoreGridErr: (step: string) => `（网格步长 ±${step} Å）`,
  quotePoreLcd: (lcd: string, err: string) => `最大内切球直径 LCD ${lcd} Å${err}`,
  quotePorePld: (pld: string, err: string) => `孔径 PLD ${pld}${err} Å（渗流二分，任意路径）`,
  quotePorePldNote: (note: string) => `PLD：${note}`,
  quotePoreCentroid: (frac: string) => `质心 ${frac}`,
  quotePoreInscribedCentre: (frac: string) => `内切球心 ${frac}`,
  quoteResidualElectrons: (n: number) => `残余电子约 ${n} e`,
  quotePore: (id: number | string, parts: string) =>
    `孔道 V${id}：${parts}：里面装的是什么？能建模还是该走掩膜/SQUEEZE？`,

  // quote.ts - solvent-accessible void (whole cell)
  quoteVoidNotComputed: "未计算",
  quoteVoidElectronsNotComputed: "电子数未计算（需要反射数据和密度积分）",
  quoteVoid: (size: string, density: string, geometryOnly: boolean) =>
    `每晶胞的溶剂可及孔道体积 ${size}、${density}：` +
    (geometryOnly ? "从结构几何看这个孔道有什么特点？" : "里面装的是什么？能建模还是该走掩膜/SQUEEZE？"),

  // quote.ts - checkCIF
  quoteAlert: (level: string, code: string, text: string) =>
    `请看 checkCIF 的 ${level} 级警报 ${code}：${text}。` +
    `这是模型真有问题，还是这颗晶体/这套数据下可以说明的情况？`,
  quoteCheckcifLevel: (level: string, codes: string) => `${level} 级：${codes}`,
  quoteCheckcifHead: (target: string | null) =>
    target ? `${target} 的 checkCIF 结果` : "checkCIF 结果",
  quoteCheckcif: (head: string, items: string) =>
    `${head}：${items}。` + `哪些是必须动模型的，哪些该写进 special details？先处理哪一个？`,

  // quote.ts - topology
  quoteTopoNets: (n: number, dims: string) => `独立网 ${n} 个（维度 ${dims}）`,
  quoteTopoRelation: (a: number, b: number, relation: string, shift: string | null, op: string | null) =>
    `网${a}↔网${b} ${relation}${shift ? `（${shift}）` : ""}${op ? ` ${op}` : ""}`,
  quoteTopoInterpenetrated: (relTxt: string) =>
    `互穿（环穿越判定）${relTxt ? `，网间对称关系：${relTxt}` : ""}`,
  quoteTopoNotInterpenetrated: (symRelated: boolean, relTxt: string) =>
    `不互穿（环穿越未发现）${symRelated ? `，但对称相关：${relTxt}` : ""}`,
  quoteTopoSymRelated: (relTxt: string) => `对称相关多网（互穿未判定）：${relTxt}`,
  quoteTopoNoMapping: "未找到网间对称映射，互穿未判定",
  quoteTopoConnectivity: (c: string, n: number) => `${c}-连接 ×${n}`,
  quoteTopoSimplifiedNet: (nNodes: number, nEdges: number, hist: string) =>
    `简化网每胞 ${nNodes} 节点 / ${nEdges} 边（${hist}）`,
  quoteTopoRcsrMulti: (symbols: string, n: number) => `RCSR ${symbols} × ${n}（${n} 个分量）`,
  quoteHelixRacemic: "外消旋",
  quoteTopoHelix: (screw: string, hand: string, pitch: string) =>
    `${screw}${hand ? ` ${hand}` : ""} 螺距 ${pitch} Å`,
  quoteTopoHelices: (items: string) => `螺旋链 ${items}`,
  quoteTopology: (parts: string) =>
    `拓扑（描述，不是判定）：${parts}：这个描述与文献 / 预期一致吗？`,

  // quote.ts - finite fragment
  quoteFragAtoms: (n: number) => `${n} 个原子`,
  quoteFragCopies: (n: number) => `${n} 份`,
  quoteFragLargestRing: (size: number, truncated: boolean) =>
    `最大无弦环 ${size} 元${truncated ? "（搜索截断）" : ""}`,
  quoteFragSphericity: (v: string) => `球形度 ${v}`,
  quoteFragAspect: (v: string) => `纵横比 ${v}`,
  quoteFragLongestAxis: (v: string) => `最长轴 ${v} Å`,
  quoteFragment: (fragment: string, labels: string, parts: string) =>
    `有限片段 ${fragment}（${labels}）：${parts}：从这些证据看它的形貌该怎么描述？`,

  // humanizeCommand.ts - exe/cmdlet -> action phrase
  cmdVerbs: {
    // crystallography executables
    shelxl: "运行 SHELXL 精修",
    shelxt: "运行 SHELXT 求解",
    shelxs: "运行 SHELXS 求解",
    platon: "运行 PLATON 检查",
    sadabs: "运行 SADABS 吸收校正",
    twinabs: "运行 TWINABS 吸收校正",
    // file reading / listing
    "get-content": "读取文件",
    type: "读取文件",
    cat: "读取文件",
    "get-childitem": "查看文件列表",
    gci: "查看文件列表",
    dir: "查看文件列表",
    ls: "查看文件列表",
    "get-item": "查看文件信息",
    "test-path": "检查路径",
    "resolve-path": "解析路径",
    "measure-object": "统计",
    "select-object": "筛选字段",
    "get-filehash": "计算文件校验和",
    head: "查看文件开头",
    tail: "查看文件末尾",
    // file writes / moves
    "set-content": "写入文件",
    "out-file": "写入文件",
    "add-content": "追加写入文件",
    "copy-item": "复制文件",
    copy: "复制文件",
    cp: "复制文件",
    xcopy: "复制文件",
    robocopy: "复制目录",
    "move-item": "移动文件",
    move: "移动文件",
    mv: "移动文件",
    "remove-item": "删除文件",
    del: "删除文件",
    rm: "删除文件",
    "new-item": "新建文件/目录",
    mkdir: "新建目录",
    md: "新建目录",
    "expand-archive": "解压文件",
    "compress-archive": "打包文件",
    tar: "解压/打包",
    "7z": "解压/打包",
    // search
    "select-string": "检索文本",
    findstr: "检索文本",
    rg: "检索文本",
    grep: "检索文本",
    // misc tooling
    git: "Git 操作",
    curl: "网络请求",
    wget: "下载文件",
    "invoke-webrequest": "网络请求",
    taskkill: "结束进程",
    "stop-process": "结束进程",
    "get-process": "查看进程",
    "set-location": "切换目录",
    cd: "切换目录",
    "write-output": "输出文本",
    echo: "输出文本",
    sed: "文本处理",
    awk: "文本处理",
    sort: "排序",
    wc: "统计行数",
  },
  cmdPyCrystalpilot: "调用 CrystalPilot 组件",
  cmdPyModule: (mod: string) => `运行 Python 模块 ${mod}`,
  cmdPySnippet: "运行 Python 片段",
  cmdPyScript: "运行 Python 脚本",
  cmdDials: (step: string) => `运行 DIALS（${step}）`,
  cmdRun: (head: string, truncated: boolean) => `运行命令：${head}${truncated ? "…" : ""}`,

  // slashCommands.ts - palette descriptions
  slashModel: "选择模型",
  slashEffort: "选择推理档位",
  slashPermissions: "权限模式",
  slashSubagents: "子代理开关",
  slashCompact: "立即压缩上下文",
  slashContext: "上下文窗口用量",
  slashStatus: "当前状态：模型、提供方、档位、权限、内核",
  slashMcp: "晶体学工具（MCP）状态",
  slashSkills: "已安装的技能",
  slashRenameArgs: "<名称>",
  slashRename: "重命名当前对话",
  slashFork: "分叉当前对话（在当前提供方/模型上继续）",
  slashStop: "中断当前回合",
  slashSettings: "打开设置：提供方、密钥、内核",

  // stages.ts - display names of the pipeline stages (STAGE_ZH itself stays
  // Chinese: it is the vocabulary situation_report emits and is parsed)
  stageNames: {
    data: "数据",
    symmetry: "定群",
    solve: "求解",
    model: "建模",
    refine: "精修",
    validate: "验证",
    deliver: "交付",
  },

  // structureClass.ts - the evidence a class suggestion rests on
  scBasisNets: (n: number, dims: string) => `${n} 个周期网（维度 ${dims}）`,
  scBasisInterpenetrated: "互穿多网（环穿越判定）",
  scBasisSymRelatedNot: "对称相关多网（不互穿）",
  scBasisSymRelatedUnknown: "对称相关多网（互穿未判定）",
  scBasisCage: (fragment: string, nAtoms: number, sphericity: string, minSphericity: number, ring: number) =>
    `最大宿主片段 ${fragment}：${nAtoms} 原子、球形度 ${sphericity}（≥ ${minSphericity}）、最大无弦环 ${ring}`,
  scBasisMacrocycle: (fragment: string, ring: number, minRing: number) =>
    `最大宿主片段 ${fragment} 的最大无弦环 ${ring} 元（≥ ${minRing}）`,
  scBasisSalt: (n: number, minAtoms: number, nGuests: number) =>
    `${n} 种 ≥ ${minAtoms} 原子的独立片段，其中 ${nGuests} 种按宿主规则算客体 / 抗衡离子`,
  scBasisSingle: (fragment: string, nAtoms: number) => `单一分子片段 ${fragment}（${nAtoms} 原子），无周期网`,
  scBasisNothing: "无周期网、无有限片段记录",

  // interactions.ts - labels, geometry names and the quote sentence
  ixLabelPipi: (ringA: string, ringB: string) => `环 ${ringA} ⋯ 环 ${ringB}`,
  ixLabelChpi: (c: string, h: string, ring: string) => `${c}–${h}···环 ${ring}`,
  ixLabelAnionPi: (anion: string, ring: string) => `${anion} ··· 环 ${ring}`,
  ixAnionFallback: "阴离子",
  ixGeomCentroidDist: "质心距",
  ixGeomNormalAngle: "法线夹角 α",
  ixGeomPerpAB: "垂直距离 a→b / b→a",
  ixGeomSlipAB: "滑移 a→b / b→a",
  ixGeomPerp: "垂直距离",
  ixGeomOffset: "偏移",
  ixGeomStrength: "强度",
  ixVerdictPass: "满足",
  ixVerdictFail: "不满足",
  ixTailHbond: "这条氢键合理吗？要不要进 HTAB 表？",
  ixTailOther: "这条相互作用可信吗？对堆积的解释有什么影响？",
  /** head = "<kind> <label><sym><intra>", notes = the H-source / boundary clauses (each with its separator) */
  ixQuote: (head: string, geom: string, verdict: string, crit: string, notes: string, tail: string) =>
    `${head}：${geom}；${verdict}${crit ? ` ${crit} ` : ""}判据${notes}。${tail}`,

  // adp.ts - reasons a displacement ellipsoid looks pathological
  adpNpd: "ADP 非正定（NPD）",
  adpAxisRatio: (ratio: string) => `椭球轴比 ${ratio}：疑未拆无序或元素指认错误`,
  adpUeqHigh: (ueq: string) => `U_eq ${ueq} 过大：需核对占有率、无序和元素指认`,
  adpUeqLow: (ueq: string) => `U_eq ${ueq} 过小：需核对元素指认、数据与标度`,

  // askCard.ts - the [prior] reply sent for an answered question card
  askPriorReply: (prefix: string, question: string, answer: string) =>
    `${prefix} 问题：${question}\n回答：${answer}`,
};

export const en: typeof zh = {
  // punctuation shared by the sentence builders below
  sepList: ", ",
  sepClause: "; ",
  sepComma: ", ",
  parens: (s: string) => ` (${s})`,

  // quote.ts - atom
  quoteAtomSymCopy: (op: string) => `symmetry copy ${op}`,
  quoteAtomAdpUnknown: "ADP not reported",
  quoteAtomOcc: (occ: string) => `occupancy ${occ}`,
  quoteAtomHead: (elem: string, label: string, facts: string) =>
    `Please look at ${elem} atom ${label} (${facts})`,
  quoteAtomStructureOnly: (head: string) =>
    `${head}: what are its coordination and geometric environment in the source CIF? (Structure only at present, no observed reflection data.)`,
  quoteAtomWithReasons: (head: string, reasons: string) =>
    `${head}: ${reasons}. Is this disorder, a wrong element, or a problem with the position itself?`,
  quoteAtomDefault: (head: string) =>
    `${head}: what do the difference density and the coordination environment around it look like?`,

  // quote.ts - difference-map peak
  quotePeakAt: (coords: string) => `fractional coordinates (${coords})`,
  quotePeakNear: (atom: string, d: string) => ` (${d} Å from ${atom})`,
  quotePeak: (at: string, near: string, height: string) =>
    `Please check the difference-density peak of ${height} eÅ⁻³ at ${at}${near}: ` +
    `is it a missing atom, a disorder component or noise? (Check the referenced node first, then refresh the peak table with inspect_map to locate it.)`,

  // quote.ts - measurement
  quoteMeasure: (text: string) =>
    `I measured ${text} in the structure (viewer reading, no esd): ` +
    `is this geometry reasonable? Does it need restraints or constraints?`,

  // quote.ts - whole structure
  quoteStructureHead: (node: string | null) => `Current model${node ? ` (node ${node})` : ""}`,
  quoteSpaceGroup: (sg: string) => `space group ${sg}`,
  quoteCell: (lengths: string, angles: string) => `cell ${lengths} / ${angles}`,
  quoteAtomsCount: (n: number) => `${n} atoms`,
  quoteParamsCount: (n: number) => `${n} parameters`,
  quoteRestraintsCount: (n: number) => `${n} restraints`,
  quoteResidualPeak: (v: string) => `residual peak ${v}`,
  quoteResidualHole: (v: string) => `residual hole ${v} eÅ⁻³`,
  quoteCompleteness: (pct: string) => `completeness ${pct}%`,
  quoteUniqueCount: (n: number) => `${n} unique reflections`,
  quoteData: (items: string) => `data ${items}`,
  quoteStructure: (head: string, items: string) =>
    `${head}: ${items}. How do you read the current state, and what should the next step be?`,

  // quote.ts - rendered frame
  quoteFrameTruncated: "display truncated, only part of the structure is shown",
  quoteFrameLayers: (layers: string) => `overlays: ${layers}`,
  quoteNodeLabel: (node: string) => `node ${node}`,
  quoteCurrentModel: "current model",
  quoteFrame: (where: string, bits: string) =>
    `This is the view I am looking at now (${where}; ${bits}). ` +
    `What in the picture deserves attention?`,

  // quote.ts - guest / counter-ion site
  quoteGuestSite: {
    cage_cavity: "inside the cage",
    channel: "in a channel",
    cavity: "in an intermolecular cavity",
    interstitial: "in a lattice interstice",
  },
  quoteGuestPosition: (site: string) => `located ${site}`,
  quoteGuestVoid: (id: number) => `void V${id}`,
  quoteGuestHostFragment: (fragment: string) => `host fragment ${fragment}`,
  quoteGuestClearance: (d: string) => `nearest clearance ${d} Å`,
  quoteGuestContact: (atom: string, hostAtom: string, op: string | null, d: string) =>
    `nearest contact ${atom}···${hostAtom}${op ? `(${op})` : ""} ${d} Å`,
  quoteGuestStraddles: "atoms straddle two regions",
  quoteGuest: (formula: string, fragment: string, copies: number, parts: string) =>
    `Guest ${formula} (${fragment}, ${copies} ${copies === 1 ? "copy" : "copies"}): ${parts}: is this assignment reasonable? How does it affect the modelling / solvent-mask decision?`,

  // quote.ts - pore (voids.json v3)
  quotePoreVolume: (v: number) => `volume ${v} Å³`,
  quotePoreDirs: (name: string, dirs: string) => `${name} (directions ${dirs})`,
  quotePoreGridErr: (step: string) => ` (grid step ±${step} Å)`,
  quotePoreLcd: (lcd: string, err: string) => `largest included-sphere diameter LCD ${lcd} Å${err}`,
  quotePorePld: (pld: string, err: string) =>
    `pore-limiting diameter PLD ${pld}${err} Å (percolation bisection, any path)`,
  quotePorePldNote: (note: string) => `PLD: ${note}`,
  quotePoreCentroid: (frac: string) => `centroid ${frac}`,
  quotePoreInscribedCentre: (frac: string) => `inscribed-sphere centre ${frac}`,
  quoteResidualElectrons: (n: number) => `about ${n} e of residual electrons`,
  quotePore: (id: number | string, parts: string) =>
    `Pore V${id}: ${parts}: what is inside it? Can it be modelled, or should it go to a solvent mask / SQUEEZE?`,

  // quote.ts - solvent-accessible void (whole cell)
  quoteVoidNotComputed: "not computed",
  quoteVoidElectronsNotComputed: "electron count not computed (needs reflection data and density integration)",
  quoteVoid: (size: string, density: string, geometryOnly: boolean) =>
    `Solvent-accessible void volume per unit cell ${size}, ${density}: ` +
    (geometryOnly
      ? "what does the structure's geometry say about this void?"
      : "what is inside it? Can it be modelled, or should it go to a solvent mask / SQUEEZE?"),

  // quote.ts - checkCIF
  quoteAlert: (level: string, code: string, text: string) =>
    `Please look at the checkCIF level ${level} alert ${code}: ${text}. ` +
    `Is this a genuine problem with the model, or a situation that can be explained for this crystal / this data set?`,
  quoteCheckcifLevel: (level: string, codes: string) => `level ${level}: ${codes}`,
  quoteCheckcifHead: (target: string | null) =>
    target ? `checkCIF result for ${target}` : "checkCIF result",
  quoteCheckcif: (head: string, items: string) =>
    `${head}: ${items}. ` +
    `Which of these require changing the model, and which belong in the special details? Which should be dealt with first?`,

  // quote.ts - topology
  quoteTopoNets: (n: number, dims: string) =>
    `${n} independent ${n === 1 ? "net" : "nets"} (dimensionality ${dims})`,
  quoteTopoRelation: (a: number, b: number, relation: string, shift: string | null, op: string | null) =>
    `net ${a} ↔ net ${b} ${relation}${shift ? ` (${shift})` : ""}${op ? ` ${op}` : ""}`,
  quoteTopoInterpenetrated: (relTxt: string) =>
    `interpenetrated (ring-crossing test)${relTxt ? `, symmetry relations between nets: ${relTxt}` : ""}`,
  quoteTopoNotInterpenetrated: (symRelated: boolean, relTxt: string) =>
    `not interpenetrated (no ring crossing found)${symRelated ? `, but symmetry-related: ${relTxt}` : ""}`,
  quoteTopoSymRelated: (relTxt: string) =>
    `symmetry-related nets (interpenetration undetermined): ${relTxt}`,
  quoteTopoNoMapping: "no symmetry mapping between the nets was found, interpenetration undetermined",
  quoteTopoConnectivity: (c: string, n: number) => `${c}-connected ×${n}`,
  quoteTopoSimplifiedNet: (nNodes: number, nEdges: number, hist: string) =>
    `simplified net per cell ${nNodes} ${nNodes === 1 ? "node" : "nodes"} / ${nEdges} ${nEdges === 1 ? "edge" : "edges"} (${hist})`,
  quoteTopoRcsrMulti: (symbols: string, n: number) => `RCSR ${symbols} × ${n} (${n} components)`,
  quoteHelixRacemic: "racemic",
  quoteTopoHelix: (screw: string, hand: string, pitch: string) =>
    `${screw}${hand ? ` ${hand}` : ""}, pitch ${pitch} Å`,
  quoteTopoHelices: (items: string) => `helical chains ${items}`,
  quoteTopology: (parts: string) =>
    `Topology (a description, not a verdict): ${parts}: does this description agree with the literature / expectations?`,

  // quote.ts - finite fragment
  quoteFragAtoms: (n: number) => `${n} atoms`,
  quoteFragCopies: (n: number) => `${n} ${n === 1 ? "copy" : "copies"}`,
  quoteFragLargestRing: (size: number, truncated: boolean) =>
    `largest chordless ring ${size}-membered${truncated ? " (search truncated)" : ""}`,
  quoteFragSphericity: (v: string) => `sphericity ${v}`,
  quoteFragAspect: (v: string) => `aspect ratio ${v}`,
  quoteFragLongestAxis: (v: string) => `longest axis ${v} Å`,
  quoteFragment: (fragment: string, labels: string, parts: string) =>
    `Finite fragment ${fragment} (${labels}): ${parts}: from this evidence, how should its shape be described?`,

  // humanizeCommand.ts - exe/cmdlet -> action phrase
  cmdVerbs: {
    // crystallography executables
    shelxl: "Run SHELXL refinement",
    shelxt: "Run SHELXT structure solution",
    shelxs: "Run SHELXS structure solution",
    platon: "Run PLATON check",
    sadabs: "Run SADABS absorption correction",
    twinabs: "Run TWINABS absorption correction",
    // file reading / listing
    "get-content": "Read file",
    type: "Read file",
    cat: "Read file",
    "get-childitem": "List files",
    gci: "List files",
    dir: "List files",
    ls: "List files",
    "get-item": "Show file information",
    "test-path": "Check path",
    "resolve-path": "Resolve path",
    "measure-object": "Count",
    "select-object": "Select fields",
    "get-filehash": "Compute file checksum",
    head: "Show start of file",
    tail: "Show end of file",
    // file writes / moves
    "set-content": "Write file",
    "out-file": "Write file",
    "add-content": "Append to file",
    "copy-item": "Copy file",
    copy: "Copy file",
    cp: "Copy file",
    xcopy: "Copy file",
    robocopy: "Copy directory",
    "move-item": "Move file",
    move: "Move file",
    mv: "Move file",
    "remove-item": "Delete file",
    del: "Delete file",
    rm: "Delete file",
    "new-item": "Create file/directory",
    mkdir: "Create directory",
    md: "Create directory",
    "expand-archive": "Extract archive",
    "compress-archive": "Create archive",
    tar: "Extract/create archive",
    "7z": "Extract/create archive",
    // search
    "select-string": "Search text",
    findstr: "Search text",
    rg: "Search text",
    grep: "Search text",
    // misc tooling
    git: "Git operation",
    curl: "Network request",
    wget: "Download file",
    "invoke-webrequest": "Network request",
    taskkill: "Terminate process",
    "stop-process": "Terminate process",
    "get-process": "List processes",
    "set-location": "Change directory",
    cd: "Change directory",
    "write-output": "Print text",
    echo: "Print text",
    sed: "Text processing",
    awk: "Text processing",
    sort: "Sort",
    wc: "Count lines",
  },
  cmdPyCrystalpilot: "Call a CrystalPilot component",
  cmdPyModule: (mod: string) => `Run Python module ${mod}`,
  cmdPySnippet: "Run a Python snippet",
  cmdPyScript: "Run a Python script",
  cmdDials: (step: string) => `Run DIALS (${step})`,
  cmdRun: (head: string, truncated: boolean) => `Run command: ${head}${truncated ? "…" : ""}`,

  // slashCommands.ts - palette descriptions
  slashModel: "Choose the model",
  slashEffort: "Choose the reasoning effort",
  slashPermissions: "Permission mode",
  slashSubagents: "Sub-agents on/off",
  slashCompact: "Compact the context now",
  slashContext: "Context window usage",
  slashStatus: "Current status: model, provider, effort, permissions, kernel",
  slashMcp: "Crystallography tools (MCP) status",
  slashSkills: "Installed skills",
  slashRenameArgs: "<name>",
  slashRename: "Rename the current conversation",
  slashFork: "Fork the current conversation (continue on the current provider/model)",
  slashStop: "Interrupt the current turn",
  slashSettings: "Open settings: providers, keys, kernel",

  // stages.ts - display names of the pipeline stages
  stageNames: {
    data: "Data",
    symmetry: "Symmetry",
    solve: "Solve",
    model: "Model",
    refine: "Refine",
    validate: "Validate",
    deliver: "Deliver",
  },

  // structureClass.ts - the evidence a class suggestion rests on
  scBasisNets: (n: number, dims: string) =>
    `${n} periodic ${n === 1 ? "net" : "nets"} (dimensionality ${dims})`,
  scBasisInterpenetrated: "interpenetrated nets (ring-crossing test)",
  scBasisSymRelatedNot: "symmetry-related nets (not interpenetrated)",
  scBasisSymRelatedUnknown: "symmetry-related nets (interpenetration undetermined)",
  scBasisCage: (fragment: string, nAtoms: number, sphericity: string, minSphericity: number, ring: number) =>
    `largest host fragment ${fragment}: ${nAtoms} atoms, sphericity ${sphericity} (≥ ${minSphericity}), largest chordless ring ${ring}`,
  scBasisMacrocycle: (fragment: string, ring: number, minRing: number) =>
    `the largest chordless ring of the largest host fragment ${fragment} is ${ring}-membered (≥ ${minRing})`,
  scBasisSalt: (n: number, minAtoms: number, nGuests: number) =>
    `${n} independent fragments with ≥ ${minAtoms} atoms, of which ${nGuests} ${nGuests === 1 ? "counts" : "count"} as guest / counter-ion by the host rule`,
  scBasisSingle: (fragment: string, nAtoms: number) =>
    `a single molecular fragment ${fragment} (${nAtoms} atoms), no periodic net`,
  scBasisNothing: "no periodic net and no finite-fragment record",

  // interactions.ts - labels, geometry names and the quote sentence
  ixLabelPipi: (ringA: string, ringB: string) => `ring ${ringA} ⋯ ring ${ringB}`,
  ixLabelChpi: (c: string, h: string, ring: string) => `${c}–${h}···ring ${ring}`,
  ixLabelAnionPi: (anion: string, ring: string) => `${anion} ··· ring ${ring}`,
  ixAnionFallback: "anion",
  ixGeomCentroidDist: "centroid distance",
  ixGeomNormalAngle: "interplanar angle α",
  ixGeomPerpAB: "perpendicular distance a→b / b→a",
  ixGeomSlipAB: "slip a→b / b→a",
  ixGeomPerp: "perpendicular distance",
  ixGeomOffset: "offset",
  ixGeomStrength: "strength",
  ixVerdictPass: "meets",
  ixVerdictFail: "does not meet",
  ixTailHbond: "Is this hydrogen bond reasonable? Should it go into the HTAB table?",
  ixTailOther: "Is this interaction credible? How does it affect the interpretation of the packing?",
  ixQuote: (head: string, geom: string, verdict: string, crit: string, notes: string, tail: string) =>
    `${head}: ${geom}; ${verdict} the criteria${crit ? ` (${crit})` : ""}${notes}. ${tail}`,

  // adp.ts - reasons a displacement ellipsoid looks pathological
  adpNpd: "ADP non-positive-definite (NPD)",
  adpAxisRatio: (ratio: string) =>
    `ellipsoid axis ratio ${ratio}: suspected unsplit disorder or wrong element assignment`,
  adpUeqHigh: (ueq: string) => `U_eq ${ueq} too large: check occupancy, disorder and element assignment`,
  adpUeqLow: (ueq: string) => `U_eq ${ueq} too small: check element assignment, data and scale`,

  // askCard.ts - the [prior] reply sent for an answered question card
  askPriorReply: (prefix: string, question: string, answer: string) =>
    `${prefix} Question: ${question}\nAnswer: ${answer}`,
};
