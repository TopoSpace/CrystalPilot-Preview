/** Quote-to-chat formatters.
 *
 * The viewer can put a reference to what you are looking at straight into
 * the composer. What makes those quotes work is that they are
 * SELF-DESCRIBING: the agent reads the message with no access to the
 * viewer's state, so a quote has to carry the evidence, not a pointer to
 * it. Two rules follow, both learned the hard way:
 *
 * - Never cite a viewer-local ordinal. `Q7` means the seventh peak in
 *   peaks.json, which is computed per node independently of the live
 *   session's diff_map_peaks table; the agent's Q7 can be a different
 *   peak. Cite position, height and nearest atom instead.
 * - Carry the numbers that made you click. A quote that says only
 *   "look at C11" throws away the U_eq the card just showed you and
 *   makes the agent re-derive the reason you asked.
 *
 * These are pure string builders so the wording can be asserted in tests
 * rather than reviewed by eye every time the card layout changes.
 */
import type {
  AnalysisTopology,
  FiniteFragment,
  GuestEntry,
  PeakEntry,
  SceneAtom,
  VoidEntry,
} from "./wbTypes";

/** Reference to a clicked atom: identity, the ADP/occupancy numbers on the
 * card, the symmetry operator when it is not the atom in the asymmetric
 * unit, and any ADP anomaly that was flagged. Ends with the open question
 * rather than an instruction - the agent decides what to run. */
export function atomQuote(
  a: SceneAtom,
  reasons: string[] = [],
  node?: string | null,
  structureOnly = false,
): string {
  const facts: string[] = [];
  if (a.sym && a.symop) facts.push(`对称拷贝 ${a.symop}`);
  facts.push(a.adp_known === false || a.u_eq === null ? "ADP 未报告" : `U_eq ${a.u_eq.toFixed(4)} Å²`);
  if (Math.abs(a.occ - 1) > 1e-3) facts.push(`占有率 ${a.occ.toFixed(3)}`);
  if (a.part) facts.push(`PART ${a.part}`);
  const head = `请看 ${a.elem} 原子 ${a.label}（${facts.join("；")}）`;
  const question = structureOnly
    ? `${head}：源 CIF 中它的配位和几何环境如何？（当前只有结构，无观测反射数据）`
    : reasons.length > 0
      ? `${head}：${reasons.join("；")}。这是无序、错元素、还是位置本身有问题？`
      : `${head}：它周围的差值密度与配位环境如何？`;
  return withAnchor(question, node, [atomIdentity(a)]);
}

function atomIdentity(a: SceneAtom): string {
  return a.sym && a.symop ? `${a.label}(${a.symop})` : a.label;
}

/** Reference to a difference-map peak. Deliberately ordinal-free. */
export function peakQuote(peak: PeakEntry, node?: string | null): string {
  const at = `分数坐标 (${peak.site.map((x) => x.toFixed(4)).join(", ")})`;
  const near = peak.nearest_atom !== null && peak.nearest_d !== null
    ? `（距 ${peak.nearest_atom} ${peak.nearest_d.toFixed(2)} Å）`
    : "";
  return withAnchor(
    `请检查${at}${near}处高 ${peak.height.toFixed(2)} eÅ⁻³ 的差值密度峰：` +
      `是缺原子、无序分量还是噪音？（先核对引用节点，再用 inspect_map 刷新峰表定位）`,
    node,
    peak.nearest_atom ? [peak.nearest_atom] : [],
  );
}

/** Reference to a click-chain measurement. The viewer computes the value
 * without an esd (the covariance matrix stays server-side), so the quote
 * says so instead of letting a bare number read as a refined quantity. */
export function measureQuote(
  text: string,
  node?: string | null,
  atoms: readonly SceneAtom[] = [],
): string {
  return withAnchor(
    `我在结构里量到 ${text}（视图读数，未带 esd）：` +
      `这个几何合理吗？需要限制/约束吗？`,
    node,
    atoms.map(atomIdentity),
  );
}

/** The whole structure's current state, for "here is where I am, what do
 * you think". Everything in it is on the header card, but retyping a cell
 * and four R factors by hand is exactly the friction that stops people
 * asking. Facts only, no verdict - the agent should reach its own. */
export function structureQuote(s: {
  node: string | null;
  spaceGroup?: string;
  cell?: { a: number; b: number; c: number;
           alpha: number; beta: number; gamma: number };
  r1: number | null;
  wr2: number | null;
  goof: number | null;
  nAtoms: number;
  nParams?: number | null;
  nRestraints?: number;
  peak?: number | null;
  hole?: number | null;
  data?: {
    r_int?: number;
    d_min?: number;
    completeness?: number;
    n_unique?: number;
  };
}): string {
  const head = `当前模型${s.node ? `（节点 ${s.node}）` : ""}`;
  const L: string[] = [];
  if (s.spaceGroup) L.push(`空间群 ${s.spaceGroup}`);
  if (s.cell) {
    const c = s.cell;
    L.push(
      `胞 ${c.a.toFixed(3)} ${c.b.toFixed(3)} ${c.c.toFixed(3)} / ` +
        `${c.alpha.toFixed(2)} ${c.beta.toFixed(2)} ${c.gamma.toFixed(2)}`,
    );
  }
  const r: string[] = [];
  if (s.r1 !== null) r.push(`R1 ${s.r1.toFixed(4)}`);
  if (s.wr2 !== null) r.push(`wR2 ${s.wr2.toFixed(4)}`);
  if (s.goof !== null) r.push(`GooF ${s.goof.toFixed(2)}`);
  if (r.length > 0) L.push(r.join("、"));
  const m: string[] = [`${s.nAtoms} 原子`];
  if (s.nParams) m.push(`${s.nParams} 参数`);
  if (s.nRestraints) m.push(`${s.nRestraints} 限制`);
  if (s.peak !== null && s.peak !== undefined) {
    m.push(`残峰 ${s.peak.toFixed(2)}`);
  }
  if (s.hole !== null && s.hole !== undefined) {
    m.push(`残洞 ${s.hole.toFixed(2)} eÅ⁻³`);
  }
  L.push(m.join("、"));
  const dd = s.data;
  if (dd) {
    const dl: string[] = [];
    if (dd.d_min !== undefined) dl.push(`d_min ${dd.d_min.toFixed(2)} Å`);
    if (dd.r_int !== undefined) dl.push(`Rint ${dd.r_int.toFixed(3)}`);
    if (dd.completeness !== undefined) {
      dl.push(`完整度 ${(dd.completeness * 100).toFixed(1)}%`);
    }
    if (dd.n_unique !== undefined) dl.push(`${dd.n_unique} 独立衍射`);
    // the data bound what R1 could ever be, so it travels with the R1
    if (dl.length > 0) L.push(`数据 ${dl.join("、")}`);
  }
  return withAnchor(
    `${head}：${L.join("；")}。你怎么看现在的状态，下一步该做什么？`,
    s.node,
  );
}

/** Caption for a rendered frame handed to the agent. The image carries the
 * geometry; this carries what the image cannot say for itself - which node
 * it is, how much of the crystal is drawn, and which evidence layers are
 * switched on, so a green blob in the picture is identifiable as Fo-Fc
 * rather than a void surface. */
export function frameQuote(opts: {
  node: string | null;
  spaceGroup?: string;
  extent: string;
  nAtoms?: number;
  truncated?: boolean;
  layers: string[];
}): string {
  const bits = [opts.extent];
  if (opts.spaceGroup) bits.push(opts.spaceGroup);
  if (opts.nAtoms !== undefined) bits.push(`${opts.nAtoms} 原子`);
  if (opts.truncated) bits.push("显示已截断，只是结构的一部分");
  if (opts.layers.length > 0) bits.push(`叠加：${opts.layers.join("、")}`);
  const where = opts.node ? `节点 ${opts.node}` : "当前模型";
  return withAnchor(
    `这是我现在在看的画面（${where}；${bits.join("；")}）。` +
      `图里有什么值得注意的？`,
    opts.node,
  );
}

/** Reference to one guest / counter-ion site of the analysis table.
 * Carries the fragment formula, the site label with its numbers and the
 * nearest host contact with its operator - never a row ordinal. */
export function guestQuote(g: GuestEntry): string {
  const site =
    { cage_cavity: "笼内", channel: "通道中", cavity: "分子间空腔", interstitial: "晶格间隙" }[g.site]
    ?? g.site;
  const parts: string[] = [`位置 ${site}`];
  if (g.void_id !== null && g.void_id !== undefined) parts.push(`孔 V${g.void_id}`);
  if (g.host_fragment) parts.push(`宿主片段 ${g.host_fragment}`);
  if (typeof g.clearance_A === "number") parts.push(`最近间隙 ${g.clearance_A.toFixed(2)} Å`);
  const c = g.nearest_host_contacts?.[0];
  if (c) {
    const op = c.sym && c.sym.replace(/\s+/g, "") !== "x,y,z" ? `（${c.sym}）` : "";
    parts.push(`最近接触 ${c.atom}···${c.host_atom}${op} ${c.d.toFixed(2)} Å`);
  }
  if (g.straddles_regions) parts.push("原子跨越两个区域");
  return `客体 ${g.formula}（${g.fragment}，${g.copies} 份）：${parts.join("、")}：这个归属合理吗？对建模/掩膜决定有什么影响？`;
}

/** Reference to one pore of the analysis table (voids.json v3).
 *
 * A centroid is quoted ONLY for a 0-D cavity: for a channel / layer /
 * network the mean of the unwrapped grid points is a point outside the
 * cell that means nothing (defect D17), so the sentence carries the
 * inscribed-sphere centre instead, and the LCD with its grid error. */
export function poreQuote(v: VoidEntry): string {
  const dim = typeof v.dimensionality === "number" ? v.dimensionality : null;
  const parts: string[] = [`体积 ${Math.round(v.volume_A3)} Å³`];
  if (dim !== null) {
    const dirs = (v.directions ?? []).map((d) => `[${d.join(" ")}]`).join(" ");
    const name = ["孤立空腔", "1-D 通道", "2-D 层", "3-D 网络"][dim] ?? `${dim}-D`;
    parts.push(dirs ? `${name}（方向 ${dirs}）` : name);
  }
  if (typeof v.lcd_A === "number") {
    const err =
      typeof v.grid_step_A === "number" ? `（网格步长 ±${v.grid_step_A.toFixed(2)} Å）` : "";
    parts.push(`最大内切球直径 LCD ${v.lcd_A.toFixed(1)} Å${err}`);
  }
  if (typeof v.pld_A === "number") {
    const err = typeof v.pld_error_A === "number" ? ` ± ${v.pld_error_A.toFixed(2)}` : "";
    parts.push(`孔径 PLD ${v.pld_A.toFixed(1)}${err} Å（渗流二分，任意路径）`);
  } else if (dim !== null && dim > 0 && v.pld_note) {
    parts.push(`PLD：${v.pld_note}`);
  }
  const frac = (f: [number, number, number]): string =>
    `(${f.map((x) => x.toFixed(3)).join(", ")})`;
  if (dim === 0 && v.centre_frac) parts.push(`质心 ${frac(v.centre_frac)}`);
  else if (v.inscribed_centre_frac) parts.push(`内切球心 ${frac(v.inscribed_centre_frac)}`);
  if (typeof v.electrons === "number") parts.push(`残余电子约 ${Math.round(v.electrons)} e`);
  return `孔道 V${v.void}：${parts.join("、")}：里面装的是什么？能建模还是该走掩膜/SQUEEZE？`;
}

/** Reference to a solvent-accessible void. */
export function voidQuote(volume: number | null, electrons: number | null, node?: string | null): string {
  const size = volume === null ? "未计算" : `${Math.round(volume)} Å³`;
  const density = electrons === null ? "电子数未计算（需要反射数据和密度积分）" : `残余电子约 ${Math.round(electrons)} e`;
  return withAnchor(
    `每晶胞的溶剂可及孔道体积 ${size}、${density}：` +
      (electrons === null ? "从结构几何看这个孔道有什么特点？" : "里面装的是什么？能建模还是该走掩膜/SQUEEZE？"),
    node,
  );
}

/** checkCIF's numeric alerts arrive with the PLAT prefix already stripped
 * (the parser keeps `934`, the panel renders it next to its level as
 * "A 934"). That is fine on a row that has a coloured A beside it and
 * useless in a sentence - a bare `934` is not something the agent can look
 * up, which is the same failure as citing `Q7`. Letter-prefixed codes like
 * ABSTM02 are already whole and are left alone. */
function platCode(code: string): string {
  return /^\d{3}$/.test(code) ? `PLAT${code}` : code;
}

/** Reference to one checkCIF alert.
 *
 * Unlike a peak ordinal, an alert code IS a stable global identifier -
 * PLAT934 means the same thing in every checkCIF report ever run - so the
 * code travels, and so does the alert's own sentence, because the numbers
 * checkCIF quotes back ("Reported 14, Expected 0") are the evidence. The
 * knowledge-base gloss on the card deliberately does NOT travel: it is our
 * text, and shipping it to the agent would be feeding it our reading of
 * the alert instead of the alert. */
export function alertQuote(a: {
  level: string;
  code: string;
  text: string;
}): string {
  return (
    `请看 checkCIF 的 ${a.level} 级警报 ${platCode(a.code)}：${a.text}。` +
    `这是模型真有问题，还是这颗晶体/这套数据下可以说明的情况？`
  );
}

/** Reference to the whole checkCIF result. Codes only for the levels that
 * warrant action, because a G-level list would bury them. */
export function checkcifQuote(opts: {
  counts: Record<string, number> | null;
  approx: boolean;
  alerts: { level: string; code: string }[];
  target?: string | null;
}): string {
  const L: string[] = [];
  if (opts.counts) {
    const c = ["A", "B", "C", "G"]
      .filter((lv) => (opts.counts as Record<string, number>)[lv] > 0)
      .map(
        (lv) =>
          `${lv} ${opts.approx ? "≥" : "×"}` +
          `${(opts.counts as Record<string, number>)[lv]}`,
      );
    if (c.length > 0) L.push(c.join("、"));
  }
  for (const lv of ["A", "B"]) {
    const codes = [
      ...new Set(
        opts.alerts
          .filter((a) => a.level === lv)
          .map((a) => platCode(a.code)),
      ),
    ];
    if (codes.length > 0) L.push(`${lv} 级：${codes.join("、")}`);
  }
  const head = opts.target ? `${opts.target} 的 checkCIF 结果` : "checkCIF 结果";
  return (
    `${head}：${L.join("；")}。` +
    `哪些是必须动模型的，哪些该写进 special details？先处理哪一个？`
  );
}

/** Human name of a net relation (chem/topology.py `relation`). */
export function relationName(r: string): string {
  return (
    { translation: "晶格平移相关", space_group_op: "空间群操作相关", independent: "晶体学独立" }[r]
    ?? r
  );
}

/** Reference to the topology block: symmetry relations are evidence, not
 * proof of interpenetration. Name the translation or operator,
 * the simplified net's node/edge counts and
 * connectivity histogram, the Systre status, the helices. Descriptions,
 * quoted with their basis so the agent can re-run analyze_packing. */
export function topologyQuote(t: AnalysisTopology): string {
  const nets = t.nets;
  const parts: string[] = [];
  if (nets.n_nets === 0) {
    parts.push("没有周期性网（分子晶体）");
  } else {
    parts.push(`独立网 ${nets.n_nets} 个（维度 ${nets.nets.map((n) => n.dimensionality).join("/")}）`);
    const rel = nets.relations.filter((r) => r.relation !== "independent");
    const relTxt = rel
      .map(
        (r) =>
          `网${r.a}↔网${r.b} ${relationName(r.relation)}${r.shift ? `（${r.shift.join(", ")}）` : ""}${r.op ? ` ${r.op}` : ""}`,
      )
      .join("；");
    if (nets.interpenetrated === true) {
      parts.push(`互穿（环穿越判定）${relTxt ? `，网间对称关系：${relTxt}` : ""}`);
    } else if (nets.interpenetrated === false && nets.n_nets > 1) {
      parts.push(`不互穿（环穿越未发现）${nets.symmetry_related ? `，但对称相关：${relTxt}` : ""}`);
    } else if (nets.symmetry_related) {
      parts.push(`对称相关多网（互穿未判定）：${relTxt}`);
    } else if (nets.n_nets > 1) {
      parts.push("未找到网间对称映射，互穿未判定");
    }
    if (nets.interlocked_1d === true) parts.push("一维链机械互锁（环穿越判定）");
    else if (nets.symmetry_related_1d) parts.push("一维链对称相关（机械互锁未判定）");
  }
  const net = t.simplified_net;
  if (net.n_nodes_per_cell > 0) {
    const hist = Object.entries(net.node_connectivity_histogram)
      .map(([c, n]) => `${c}-连接 ×${n}`)
      .join("、");
    parts.push(`简化网每胞 ${net.n_nodes_per_cell} 节点 / ${net.n_edges_per_cell} 边（${hist}）`);
    const syms = net.rcsr_symbols ?? [];
    parts.push(
      syms.length > 1
        ? `RCSR ${Array.from(new Set(syms)).join(" / ")} × ${syms.length}（${syms.length} 个分量）`
        : net.rcsr_symbol
          ? `RCSR ${net.rcsr_symbol}`
          : net.rcsr_status,
    );
  }
  if (t.helices.length) {
    parts.push(
      `螺旋链 ${t.helices
        .map(
          (h) =>
            `${h.screw}${h.racemic ? " 外消旋" : h.handedness === "right" ? " 右手" : h.handedness === "left" ? " 左手" : ""} 螺距 ${h.pitch_A.toFixed(2)} Å`,
        )
        .join("；")}`,
    );
  }
  return `拓扑（描述，不是判定）：${parts.join("；")}：这个描述与文献 / 预期一致吗？`;
}

/** Reference to one finite fragment of the topology block: atom count, host
 * or guest, copies per cell, the largest chordless ring and the shape
 * evidence (sphericity, aspect, longest axis) - the numbers a shape word
 * would have to rest on; the word itself is left to the reader. */
export function fragmentQuote(f: FiniteFragment): string {
  const parts: string[] = [`${f.n_atoms} 个原子`, f.role === "host" ? "宿主" : "客体", `${f.copies} 份`];
  const c = f.largest_cycle;
  if (c.size) parts.push(`最大无弦环 ${c.size} 元${c.truncated ? "（搜索截断）" : ""}`);
  else parts.push("无环");
  if (f.shape) {
    if (typeof f.shape.sphericity === "number") parts.push(`球形度 ${f.shape.sphericity.toFixed(2)}`);
    if (f.shape.aspect && f.shape.aspect.length === 2)
      parts.push(`纵横比 ${f.shape.aspect.map((x) => x.toFixed(2)).join(" / ")}`);
    if (typeof f.shape.longest_axis_A === "number") parts.push(`最长轴 ${f.shape.longest_axis_A.toFixed(1)} Å`);
  }
  const labels = f.asu_labels.slice(0, 6).join(" ") + (f.asu_labels.length > 6 ? " …" : "");
  return `有限片段 ${f.fragment}（${labels}）：${parts.join("、")}：从这些证据看它的形貌该怎么描述？`;
}

/** Machine-readable anchor appended to a quote (R6): `[anchor node=n0025
 * atoms=O1,N2(-x,y+1/2,-z)]`. The prose before it stays the human-readable
 * evidence; the anchor lets the agent call get_geometry / analyze_packing on
 * exactly this node and these atoms without re-deriving them. Atoms carry
 * their operator in parentheses when they are symmetry images. */
export function anchor(node: string | null | undefined, atoms: readonly string[] = []): string {
  if (!node) return "";
  const list = atoms.map((a) => a.replace(/\s+/g, "")).filter((a) => a !== "");
  return `[anchor node=${node}${list.length > 0 ? ` atoms=${list.join(",")}` : ""}]`;
}

export function withAnchor(
  text: string,
  node: string | null | undefined,
  atoms: readonly string[] = [],
): string {
  const a = anchor(node, atoms);
  return a === "" ? text : `${text} ${a}`;
}

export const ANCHOR_RE = /\[anchor ([^\]]+)\]/g;

export interface AnchorInfo {
  node: string | null;
  atoms: string[];
}

/** Parse one anchor's body (`node=n0025 atoms=O1,N2(-x,y,-z)`). */
export function parseAnchor(body: string): AnchorInfo {
  const node = /node=(\S+)/.exec(body)?.[1] ?? null;
  const atomsRaw = /atoms=(\S+)/.exec(body)?.[1] ?? "";
  // split on commas that are not inside parentheses (operators carry commas)
  const atoms: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of atomsRaw) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      if (cur) atoms.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  if (cur) atoms.push(cur);
  return { node, atoms };
}

/** One `[anchor …]` token as it sits in the composer text (round-3 R6:
 * the composer shows these as removable chips; the text stays the source
 * of truth so a plain textarea and a copy-paste still work). */
export interface AnchorToken {
  token: string;
  node: string | null;
  atoms: string[];
}

export function anchorTokens(text: string): AnchorToken[] {
  const out: AnchorToken[] = [];
  for (const m of text.matchAll(ANCHOR_RE)) {
    const a = parseAnchor(m[1]);
    out.push({ token: m[0], node: a.node, atoms: a.atoms });
  }
  return out;
}

/** Remove the first occurrence of `token` and the one space that joined
 * it to its neighbour, so the sentence closes up instead of keeping a
 * double space or a dangling one at the end. */
export function removeAnchorToken(text: string, token: string): string {
  const i = text.indexOf(token);
  if (i < 0) return text;
  let start = i;
  let end = i + token.length;
  if (start > 0 && text[start - 1] === " ") start -= 1;
  else if (end < text.length && text[end] === " ") end += 1;
  return text.slice(0, start) + text.slice(end);
}
