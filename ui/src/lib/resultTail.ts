/** Robust parsing of MCP tool `result_tail` strings.
 *
 * result_tail is the LAST N chars of the tool result JSON (2000 for most
 * tools; checkCIF/validation tools keep the full result since core.py's
 * structured-tool exception) - old transcripts and generic tools may be
 * head-truncated, so JSON.parse can fail; fall back to regex extraction
 * of the crystallographically interesting keys.
 *
 * Real shapes (workbench transcripts): {"ok":true,"summary":{"r1_strong":…,
 * "wr2":…,"goof":…,"n_atoms":…,"node":"n0013","branch":"…"},…}. Metric keys
 * appear at varying depths (run_shelxl nests under summary.shelxl); arrays
 * (history, diff_map_peaks) must be skipped so stale per-round metrics never
 * win over the top-level result.
 *
 * Two families of look-alike keys are NOT model metrics and are skipped
 * (round-2 evidence D20): score containers - validate_structure's
 * `confidence.breakdown.{r1: -13.4, goof: 0.0}` are penalty points, and the
 * turn digest once printed them as "R1 0.2293→-13.4000" - and delta blocks
 * (`delta_b_minus_a.r1_strong` from compare_nodes). On top of that every
 * number is range-checked: R factors are fractions in [0, 1] and a GooF is
 * strictly positive; anything else is dropped rather than displayed.
 */

export interface ResultSummary {
  ok?: boolean;
  node?: string;
  branch?: string;
  r1?: number;
  wr2?: number;
  goof?: number;
  nAtoms?: number;
  /** Peak of the Fo−Fc map after this step (e Å⁻³). */
  diffMapMax?: number;
  nParams?: number;
  /** Tool declared it did not change refinement state (run_shelxl, list…). */
  noStateChange?: boolean;
  /** Full parsed object when JSON.parse succeeded. */
  parsed?: unknown;
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Object keys whose subtree holds scores / penalties / differences rather
 * than metrics of the current model. Exported for the tests. */
export const NON_METRIC_CONTAINERS: ReadonlySet<string> = new Set([
  // round-3 WP1 status envelope: execution / verdict / state change live
  // here, never model metrics
  "tool_status",
  "breakdown",
  "confidence",
  "score",
  "scores",
  "grade",
  "grading",
  "penalty",
  "penalties",
]);

export function isNonMetricContainer(key: string): boolean {
  return NON_METRIC_CONTAINERS.has(key) || key.startsWith("delta");
}

/** Breadth-first search (objects only, arrays and non-metric containers
 * skipped) for the first value of any of the given keys, shallowest wins. */
function bfsFind(root: Record<string, unknown>, keys: string[]): unknown {
  const queue: Record<string, unknown>[] = [root];
  let depth = 0;
  while (queue.length > 0 && depth < 5) {
    const next: Record<string, unknown>[] = [];
    for (const obj of queue) {
      for (const key of keys) {
        if (key in obj && obj[key] !== null && obj[key] !== undefined) {
          return obj[key];
        }
      }
      for (const [k, v] of Object.entries(obj)) {
        if (isObj(v) && !isNonMetricContainer(k)) next.push(v);
      }
    }
    queue.length = 0;
    queue.push(...next);
    depth += 1;
  }
  return undefined;
}

function asNumber(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

/** R factors are fractions (0.0948), never percentages or penalties. */
function asRFactor(v: unknown): number | undefined {
  const n = asNumber(v);
  return n !== undefined && n >= 0 && n <= 1 ? n : undefined;
}

/** A goodness of fit is strictly positive (0.0 only ever means "no penalty"). */
function asGoof(v: unknown): number | undefined {
  const n = asNumber(v);
  return n !== undefined && n > 0 ? n : undefined;
}

function fromParsed(parsed: Record<string, unknown>): ResultSummary {
  const out: ResultSummary = { parsed };
  const ok = bfsFind(parsed, ["ok"]);
  if (typeof ok === "boolean") out.ok = ok;
  const node = bfsFind(parsed, ["node", "final_node"]);
  if (typeof node === "string") out.node = node;
  const branch = bfsFind(parsed, ["branch"]);
  if (typeof branch === "string") out.branch = branch;
  const r1 = asRFactor(bfsFind(parsed, ["r1_strong", "r1_after", "r1"]));
  if (r1 !== undefined) out.r1 = r1;
  const wr2 = asRFactor(bfsFind(parsed, ["wr2", "wr2_after"]));
  if (wr2 !== undefined) out.wr2 = wr2;
  const goof = asGoof(bfsFind(parsed, ["goof", "goof_after"]));
  if (goof !== undefined) out.goof = goof;
  const nAtoms = asNumber(bfsFind(parsed, ["n_atoms"]));
  if (nAtoms !== undefined) out.nAtoms = nAtoms;
  const diffMapMax = asNumber(bfsFind(parsed, ["diff_map_max"]));
  if (diffMapMax !== undefined) out.diffMapMax = diffMapMax;
  const nParams = asNumber(bfsFind(parsed, ["n_params"]));
  if (nParams !== undefined) out.nParams = nParams;
  const nsc = bfsFind(parsed, ["no_state_change"]);
  if (typeof nsc === "boolean") out.noStateChange = nsc;
  return out;
}

/** Remove `"<container>": { … }` spans (balanced braces, string-aware) from
 * a possibly truncated JSON tail so the regex fallback cannot read a score
 * or delta as a metric. An unterminated container swallows the rest. */
export function stripNonMetricContainers(tail: string): string {
  const open = /"([A-Za-z0-9_]+)"\s*:\s*\{/g;
  let out = "";
  let pos = 0;
  for (;;) {
    open.lastIndex = pos;
    const m = open.exec(tail);
    if (!m) break;
    if (!isNonMetricContainer(m[1])) {
      out += tail.slice(pos, m.index + m[0].length);
      pos = m.index + m[0].length;
      continue;
    }
    out += tail.slice(pos, m.index);
    let i = m.index + m[0].length;
    let depth = 1;
    let inStr = false;
    for (; i < tail.length && depth > 0; i++) {
      const c = tail[i];
      if (inStr) {
        if (c === "\\") i += 1;
        else if (c === '"') inStr = false;
      } else if (c === '"') inStr = true;
      else if (c === "{") depth += 1;
      else if (c === "}") depth -= 1;
    }
    pos = i;
  }
  return out + tail.slice(pos);
}

function rxNum(tail: string, key: string): number | undefined {
  const m = tail.match(new RegExp(`"${key}"\\s*:\\s*(-?[\\d.]+)`));
  if (!m) return undefined;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : undefined;
}

function rxStr(tail: string, key: string): string | undefined {
  const m = tail.match(new RegExp(`"${key}"\\s*:\\s*"([^"]+)"`));
  return m ? m[1] : undefined;
}

function fromRegex(rawTail: string): ResultSummary {
  const tail = stripNonMetricContainers(rawTail);
  const out: ResultSummary = {};
  const ok = tail.match(/"ok"\s*:\s*(true|false)/);
  if (ok) out.ok = ok[1] === "true";
  const node = rxStr(tail, "node") ?? rxStr(tail, "final_node");
  if (node !== undefined) out.node = node;
  const branch = rxStr(tail, "branch");
  if (branch !== undefined) out.branch = branch;
  const r1 = asRFactor(
    rxNum(tail, "r1_strong") ?? rxNum(tail, "r1_after") ?? rxNum(tail, "r1"),
  );
  if (r1 !== undefined) out.r1 = r1;
  const wr2 = asRFactor(rxNum(tail, "wr2"));
  if (wr2 !== undefined) out.wr2 = wr2;
  const goof = asGoof(rxNum(tail, "goof"));
  if (goof !== undefined) out.goof = goof;
  const nAtoms = rxNum(tail, "n_atoms");
  if (nAtoms !== undefined) out.nAtoms = nAtoms;
  const diffMapMax = rxNum(tail, "diff_map_max");
  if (diffMapMax !== undefined) out.diffMapMax = diffMapMax;
  const nParams = rxNum(tail, "n_params");
  if (nParams !== undefined) out.nParams = nParams;
  const nsc = tail.match(/"no_state_change"\s*:\s*(true|false)/);
  if (nsc) out.noStateChange = nsc[1] === "true";
  return out;
}

export function safeParseResultTail(
  tail: string | null | undefined,
): ResultSummary | null {
  if (!tail) return null;
  try {
    const parsed: unknown = JSON.parse(tail);
    if (isObj(parsed)) return fromParsed(parsed);
    return { parsed };
  } catch {
    return fromRegex(tail);
  }
}
