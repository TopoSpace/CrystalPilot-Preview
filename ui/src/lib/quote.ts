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
import { t } from "./i18n";

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
  if (a.sym && a.symop) facts.push(t.libs.quoteAtomSymCopy(a.symop));
  facts.push(a.adp_known === false || a.u_eq === null ? t.libs.quoteAtomAdpUnknown : `U_eq ${a.u_eq.toFixed(4)} Å²`);
  if (Math.abs(a.occ - 1) > 1e-3) facts.push(t.libs.quoteAtomOcc(a.occ.toFixed(3)));
  if (a.part) facts.push(`PART ${a.part}`);
  const head = t.libs.quoteAtomHead(a.elem, a.label, facts.join(t.libs.sepClause));
  const question = structureOnly
    ? t.libs.quoteAtomStructureOnly(head)
    : reasons.length > 0
      ? t.libs.quoteAtomWithReasons(head, reasons.join(t.libs.sepClause))
      : t.libs.quoteAtomDefault(head);
  return withAnchor(question, node, [atomIdentity(a)]);
}

function atomIdentity(a: SceneAtom): string {
  return a.sym && a.symop ? `${a.label}(${a.symop})` : a.label;
}

/** Reference to a difference-map peak. Deliberately ordinal-free. */
export function peakQuote(peak: PeakEntry, node?: string | null): string {
  const at = t.libs.quotePeakAt(peak.site.map((x) => x.toFixed(4)).join(", "));
  const near = peak.nearest_atom !== null && peak.nearest_d !== null
    ? t.libs.quotePeakNear(peak.nearest_atom, peak.nearest_d.toFixed(2))
    : "";
  return withAnchor(
    t.libs.quotePeak(at, near, peak.height.toFixed(2)),
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
    t.libs.quoteMeasure(text),
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
  const head = t.libs.quoteStructureHead(s.node);
  const L: string[] = [];
  if (s.spaceGroup) L.push(t.libs.quoteSpaceGroup(s.spaceGroup));
  if (s.cell) {
    const c = s.cell;
    L.push(
      t.libs.quoteCell(
        `${c.a.toFixed(3)} ${c.b.toFixed(3)} ${c.c.toFixed(3)}`,
        `${c.alpha.toFixed(2)} ${c.beta.toFixed(2)} ${c.gamma.toFixed(2)}`,
      ),
    );
  }
  const r: string[] = [];
  if (s.r1 !== null) r.push(`R1 ${s.r1.toFixed(4)}`);
  if (s.wr2 !== null) r.push(`wR2 ${s.wr2.toFixed(4)}`);
  if (s.goof !== null) r.push(`GooF ${s.goof.toFixed(2)}`);
  if (r.length > 0) L.push(r.join(t.libs.sepList));
  const m: string[] = [t.libs.quoteAtomsCount(s.nAtoms)];
  if (s.nParams) m.push(t.libs.quoteParamsCount(s.nParams));
  if (s.nRestraints) m.push(t.libs.quoteRestraintsCount(s.nRestraints));
  if (s.peak !== null && s.peak !== undefined) {
    m.push(t.libs.quoteResidualPeak(s.peak.toFixed(2)));
  }
  if (s.hole !== null && s.hole !== undefined) {
    m.push(t.libs.quoteResidualHole(s.hole.toFixed(2)));
  }
  L.push(m.join(t.libs.sepList));
  const dd = s.data;
  if (dd) {
    const dl: string[] = [];
    if (dd.d_min !== undefined) dl.push(`d_min ${dd.d_min.toFixed(2)} Å`);
    if (dd.r_int !== undefined) dl.push(`Rint ${dd.r_int.toFixed(3)}`);
    if (dd.completeness !== undefined) {
      dl.push(t.libs.quoteCompleteness((dd.completeness * 100).toFixed(1)));
    }
    if (dd.n_unique !== undefined) dl.push(t.libs.quoteUniqueCount(dd.n_unique));
    // the data bound what R1 could ever be, so it travels with the R1
    if (dl.length > 0) L.push(t.libs.quoteData(dl.join(t.libs.sepList)));
  }
  return withAnchor(
    t.libs.quoteStructure(head, L.join(t.libs.sepClause)),
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
  if (opts.nAtoms !== undefined) bits.push(t.libs.quoteAtomsCount(opts.nAtoms));
  if (opts.truncated) bits.push(t.libs.quoteFrameTruncated);
  if (opts.layers.length > 0) bits.push(t.libs.quoteFrameLayers(opts.layers.join(t.libs.sepList)));
  const where = opts.node ? t.libs.quoteNodeLabel(opts.node) : t.libs.quoteCurrentModel;
  return withAnchor(
    t.libs.quoteFrame(where, bits.join(t.libs.sepClause)),
    opts.node,
  );
}

/** Reference to one guest / counter-ion site of the analysis table.
 * Carries the fragment formula, the site label with its numbers and the
 * nearest host contact with its operator - never a row ordinal. */
export function guestQuote(g: GuestEntry): string {
  const site = t.libs.quoteGuestSite[g.site] ?? g.site;
  const parts: string[] = [t.libs.quoteGuestPosition(site)];
  if (g.void_id !== null && g.void_id !== undefined) parts.push(t.libs.quoteGuestVoid(g.void_id));
  if (g.host_fragment) parts.push(t.libs.quoteGuestHostFragment(g.host_fragment));
  if (typeof g.clearance_A === "number") parts.push(t.libs.quoteGuestClearance(g.clearance_A.toFixed(2)));
  const c = g.nearest_host_contacts?.[0];
  if (c) {
    const op = c.sym && c.sym.replace(/\s+/g, "") !== "x,y,z" ? c.sym : null;
    parts.push(t.libs.quoteGuestContact(c.atom, c.host_atom, op, c.d.toFixed(2)));
  }
  if (g.straddles_regions) parts.push(t.libs.quoteGuestStraddles);
  return t.libs.quoteGuest(g.formula, g.fragment, g.copies, parts.join(t.libs.sepList));
}

/** Reference to one pore of the analysis table (voids.json v3).
 *
 * A centroid is quoted ONLY for a 0-D cavity: for a channel / layer /
 * network the mean of the unwrapped grid points is a point outside the
 * cell that means nothing (defect D17), so the sentence carries the
 * inscribed-sphere centre instead, and the LCD with its grid error. */
export function poreQuote(v: VoidEntry): string {
  const dim = typeof v.dimensionality === "number" ? v.dimensionality : null;
  const parts: string[] = [t.libs.quotePoreVolume(Math.round(v.volume_A3))];
  if (dim !== null) {
    const dirs = (v.directions ?? []).map((d) => `[${d.join(" ")}]`).join(" ");
    const name = t.anDim[dim] ?? `${dim}-D`;
    parts.push(dirs ? t.libs.quotePoreDirs(name, dirs) : name);
  }
  if (typeof v.lcd_A === "number") {
    const err =
      typeof v.grid_step_A === "number" ? t.libs.quotePoreGridErr(v.grid_step_A.toFixed(2)) : "";
    parts.push(t.libs.quotePoreLcd(v.lcd_A.toFixed(1), err));
  }
  if (typeof v.pld_A === "number") {
    const err = typeof v.pld_error_A === "number" ? ` ± ${v.pld_error_A.toFixed(2)}` : "";
    parts.push(t.libs.quotePorePld(v.pld_A.toFixed(1), err));
  } else if (dim !== null && dim > 0 && v.pld_note) {
    parts.push(t.libs.quotePorePldNote(v.pld_note));
  }
  const frac = (f: [number, number, number]): string =>
    `(${f.map((x) => x.toFixed(3)).join(", ")})`;
  if (dim === 0 && v.centre_frac) parts.push(t.libs.quotePoreCentroid(frac(v.centre_frac)));
  else if (v.inscribed_centre_frac) parts.push(t.libs.quotePoreInscribedCentre(frac(v.inscribed_centre_frac)));
  if (typeof v.electrons === "number") parts.push(t.libs.quoteResidualElectrons(Math.round(v.electrons)));
  return t.libs.quotePore(v.void, parts.join(t.libs.sepList));
}

/** Reference to a solvent-accessible void. */
export function voidQuote(volume: number | null, electrons: number | null, node?: string | null): string {
  const size = volume === null ? t.libs.quoteVoidNotComputed : `${Math.round(volume)} Å³`;
  const density = electrons === null
    ? t.libs.quoteVoidElectronsNotComputed
    : t.libs.quoteResidualElectrons(Math.round(electrons));
  return withAnchor(
    t.libs.quoteVoid(size, density, electrons === null),
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
  return t.libs.quoteAlert(a.level, platCode(a.code), a.text);
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
    if (c.length > 0) L.push(c.join(t.libs.sepList));
  }
  for (const lv of ["A", "B"]) {
    const codes = [
      ...new Set(
        opts.alerts
          .filter((a) => a.level === lv)
          .map((a) => platCode(a.code)),
      ),
    ];
    if (codes.length > 0) L.push(t.libs.quoteCheckcifLevel(lv, codes.join(t.libs.sepList)));
  }
  const head = t.libs.quoteCheckcifHead(opts.target ?? null);
  return t.libs.quoteCheckcif(head, L.join(t.libs.sepClause));
}

/** Human name of a net relation (chem/topology.py `relation`). */
export function relationName(r: string): string {
  return t.anRelation[r] ?? r;
}

/** Reference to the topology block: symmetry relations are evidence, not
 * proof of interpenetration. Name the translation or operator,
 * the simplified net's node/edge counts and
 * connectivity histogram, the Systre status, the helices. Descriptions,
 * quoted with their basis so the agent can re-run analyze_packing. */
export function topologyQuote(topo: AnalysisTopology): string {
  const nets = topo.nets;
  const parts: string[] = [];
  if (nets.n_nets === 0) {
    parts.push(t.anNoNets);
  } else {
    parts.push(t.libs.quoteTopoNets(nets.n_nets, nets.nets.map((n) => n.dimensionality).join("/")));
    const rel = nets.relations.filter((r) => r.relation !== "independent");
    const relTxt = rel
      .map((r) =>
        t.libs.quoteTopoRelation(r.a, r.b, relationName(r.relation), r.shift ? r.shift.join(", ") : null, r.op),
      )
      .join(t.libs.sepClause);
    if (nets.interpenetrated === true) {
      parts.push(t.libs.quoteTopoInterpenetrated(relTxt));
    } else if (nets.interpenetrated === false && nets.n_nets > 1) {
      parts.push(t.libs.quoteTopoNotInterpenetrated(nets.symmetry_related === true, relTxt));
    } else if (nets.symmetry_related) {
      parts.push(t.libs.quoteTopoSymRelated(relTxt));
    } else if (nets.n_nets > 1) {
      parts.push(t.libs.quoteTopoNoMapping);
    }
    if (nets.interlocked_1d === true) parts.push(t.anInterlockedYes);
    else if (nets.symmetry_related_1d) parts.push(t.anInterlocked);
  }
  const net = topo.simplified_net;
  if (net.n_nodes_per_cell > 0) {
    const hist = Object.entries(net.node_connectivity_histogram)
      .map(([c, n]) => t.libs.quoteTopoConnectivity(c, n))
      .join(t.libs.sepList);
    parts.push(t.libs.quoteTopoSimplifiedNet(net.n_nodes_per_cell, net.n_edges_per_cell, hist));
    const syms = net.rcsr_symbols ?? [];
    parts.push(
      syms.length > 1
        ? t.libs.quoteTopoRcsrMulti(Array.from(new Set(syms)).join(" / "), syms.length)
        : net.rcsr_symbol
          ? `RCSR ${net.rcsr_symbol}`
          : net.rcsr_status,
    );
  }
  if (topo.helices.length) {
    parts.push(
      t.libs.quoteTopoHelices(
        topo.helices
          .map((h) => {
            const hand = h.racemic
              ? t.libs.quoteHelixRacemic
              : h.handedness === "right"
                ? t.anHand.right
                : h.handedness === "left"
                  ? t.anHand.left
                  : "";
            return t.libs.quoteTopoHelix(h.screw, hand, h.pitch_A.toFixed(2));
          })
          .join(t.libs.sepClause),
      ),
    );
  }
  return t.libs.quoteTopology(parts.join(t.libs.sepClause));
}

/** Reference to one finite fragment of the topology block: atom count, host
 * or guest, copies per cell, the largest chordless ring and the shape
 * evidence (sphericity, aspect, longest axis) - the numbers a shape word
 * would have to rest on; the word itself is left to the reader. */
export function fragmentQuote(f: FiniteFragment): string {
  const parts: string[] = [
    t.libs.quoteFragAtoms(f.n_atoms),
    f.role === "host" ? t.anHostRole : t.anGuestRole,
    t.libs.quoteFragCopies(f.copies),
  ];
  const c = f.largest_cycle;
  if (c.size) parts.push(t.libs.quoteFragLargestRing(c.size, c.truncated));
  else parts.push(t.anNoRing);
  if (f.shape) {
    if (typeof f.shape.sphericity === "number") parts.push(t.libs.quoteFragSphericity(f.shape.sphericity.toFixed(2)));
    if (f.shape.aspect && f.shape.aspect.length === 2)
      parts.push(t.libs.quoteFragAspect(f.shape.aspect.map((x) => x.toFixed(2)).join(" / ")));
    if (typeof f.shape.longest_axis_A === "number") parts.push(t.libs.quoteFragLongestAxis(f.shape.longest_axis_A.toFixed(1)));
  }
  const labels = f.asu_labels.slice(0, 6).join(" ") + (f.asu_labels.length > 6 ? " …" : "");
  return t.libs.quoteFragment(f.fragment, labels, parts.join(t.libs.sepList));
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
