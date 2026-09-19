/** checkCIF alert extraction from tool events (P4, 验证 tab).
 *
 * run_checkcif / submit_iucr_checkcif summaries carry
 * `alerts: [{code,type,level,text,kb:{meaning,causes,remedy}}]` + `counts`.
 * checkCIF tools now keep their FULL result JSON in result_tail (core.py
 * structured-tool exception), so full JSON.parse is the normal path. The
 * salvage fallback remains for OLD transcripts recorded under the 2000-char
 * tail: it scans for balanced `{"code": …}` objects (string/escape aware)
 * and parses each - the result is then flagged `partial` and counts become
 * a lower bound.
 */
import type { ChatItem, ToolCardItem } from "../state/threadReducer";

export type AlertLevel = "A" | "B" | "C" | "G";

export const ALERT_LEVELS: AlertLevel[] = ["A", "B", "C", "G"];

export interface CheckcifKb {
  meaning?: string;
  causes?: string;
  remedy?: string;
}

export interface CheckcifAlert {
  code: string;
  type?: number;
  level: AlertLevel;
  text: string;
  kb?: CheckcifKb;
}

export interface CheckcifSource {
  kind: "node" | "delivery" | "file";
  target: string;
  node: string | null;
  revision: number | null;
  delivery_revision: number | null;
}

export interface CheckcifData {
  execution?: "running" | "completed" | "failed" | "timeout" | "cancelled";
  reportStatus?: "complete" | "partial" | "missing";
  error?: string | null;
  failureReason?: string | null;
  source?: CheckcifSource | null;
  checkedAt?: string | null;
  alerts: CheckcifAlert[];
  /** null ⇒ true counts unknown (head-truncated tail). */
  counts: Record<AlertLevel, number> | null;
  /** Lower-bound counts derived from the salvaged alerts. */
  salvagedCounts: Record<AlertLevel, number>;
  partial: boolean;
  target: string | null;
  note: string | null;
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function parseCheckcifSource(value: unknown): CheckcifSource | null {
  if (!isObj(value) || typeof value.target !== "string") return null;
  if (value.kind !== "node" && value.kind !== "delivery" && value.kind !== "file") return null;
  const revision = (n: unknown): number | null =>
    typeof n === "number" && Number.isSafeInteger(n) && n > 0 ? n : null;
  return { kind: value.kind, target: value.target,
    node: typeof value.node === "string" ? value.node : null,
    revision: revision(value.revision), delivery_revision: revision(value.delivery_revision) };
}

export type CheckcifOriginStatus = "same_node" | "different_node" | "outdated_delivery" | "unknown";

export function checkcifOriginStatus(
  data: CheckcifData | null,
  viewedNode: string | null,
  currentTarget?: CheckcifSource | null,
): CheckcifOriginStatus {
  const source = data?.source;
  if (!source?.node || !viewedNode || currentTarget === null) return "unknown";
  if (currentTarget && (source.node !== currentTarget.node
      || source.delivery_revision !== currentTarget.delivery_revision
      || source.revision !== currentTarget.revision)) return "outdated_delivery";
  return source.node === viewedNode ? "same_node" : "different_node";
}

function asLevel(v: unknown): AlertLevel | null {
  return v === "A" || v === "B" || v === "C" || v === "G" ? v : null;
}

function toAlert(v: unknown): CheckcifAlert | null {
  if (!isObj(v)) return null;
  const level = asLevel(v.level);
  if (typeof v.code !== "string" || level === null) return null;
  const alert: CheckcifAlert = {
    code: v.code,
    level,
    text: typeof v.text === "string" ? v.text : "",
  };
  if (typeof v.type === "number") alert.type = v.type;
  if (isObj(v.kb)) {
    const kb: CheckcifKb = {};
    if (typeof v.kb.meaning === "string") kb.meaning = v.kb.meaning;
    if (typeof v.kb.causes === "string") kb.causes = v.kb.causes;
    if (typeof v.kb.remedy === "string") kb.remedy = v.kb.remedy;
    alert.kb = kb;
  }
  return alert;
}

function countByLevel(alerts: CheckcifAlert[]): Record<AlertLevel, number> {
  const counts: Record<AlertLevel, number> = { A: 0, B: 0, C: 0, G: 0 };
  for (const a of alerts) counts[a.level] += 1;
  return counts;
}

function toCounts(v: unknown): Record<AlertLevel, number> | null {
  if (!isObj(v) || !ALERT_LEVELS.some((lv) => lv in v)) return null;
  const out: Record<AlertLevel, number> = { A: 0, B: 0, C: 0, G: 0 };
  for (const lv of ALERT_LEVELS) {
    if (!(lv in v)) continue;
    const n = v[lv];
    if (typeof n !== "number" || !Number.isSafeInteger(n) || n < 0) return null;
    out[lv] = n;
  }
  return out;
}

/** Balanced-brace slice starting at `start` ("{" position); string-aware. */
function balancedSlice(s: string, start: number): string | null {
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < s.length; i += 1) {
    const ch = s[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return s.slice(start, i + 1);
    }
  }
  return null;
}

/** Salvage complete alert objects from a (possibly truncated) tail. */
function salvageAlerts(tail: string): CheckcifAlert[] {
  const out: CheckcifAlert[] = [];
  let from = 0;
  for (;;) {
    const at = tail.indexOf('{"code"', from);
    if (at < 0) break;
    const slice = balancedSlice(tail, at);
    if (slice === null) break; // truncated at the very end
    try {
      const alert = toAlert(JSON.parse(slice));
      if (alert) out.push(alert);
    } catch {
      /* mangled fragment */
    }
    from = at + slice.length;
  }
  return out;
}

function rxStr(tail: string, key: string): string | null {
  const m = tail.match(new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`));
  if (!m) return null;
  try {
    return JSON.parse(`"${m[1]}"`) as string;
  } catch {
    return m[1];
  }
}

export function parseCheckcifTail(
  tail: string | null | undefined,
): CheckcifData | null {
  if (!tail) return null;
  // 1. intact JSON
  try {
    const parsed: unknown = JSON.parse(tail);
    if (isObj(parsed)) {
      const s = isObj(parsed.summary) ? parsed.summary : parsed;
      const execution = s.execution_status;
      const reportStatus = s.report_status;
      if ((execution !== undefined && execution !== "completed")
          || (reportStatus !== undefined && reportStatus !== "complete")) {
        return {
          execution: execution === "running" || execution === "timeout" || execution === "cancelled"
            ? execution : "failed",
          reportStatus: reportStatus === "partial" ? "partial" : "missing",
          error: typeof s.error === "string" ? s.error : typeof parsed.error === "string" ? parsed.error : null,
          failureReason: typeof s.failure_reason === "string" ? s.failure_reason : null,
          alerts: [], counts: null, salvagedCounts: { A: 0, B: 0, C: 0, G: 0 }, partial: false,
          target: typeof s.target === "string" ? s.target : null,
          source: parseCheckcifSource(s.source),
          checkedAt: typeof s.checked_at === "string" ? s.checked_at : null,
          note: typeof s.note === "string" ? s.note : null,
        };
      }
      if (parsed.ok === false || parsed.isError === true || s.ok === false) return null;
      const rawAlerts = Array.isArray(s.alerts) ? s.alerts : null;
      const alerts = (rawAlerts ?? []).map(toAlert).filter((a): a is CheckcifAlert => a !== null);
      const salvagedCounts = countByLevel(alerts);
      let counts = toCounts(s.counts);
      if (rawAlerts === null && counts === null) return null;
      const emptyCounts = isObj(s.counts) && Object.keys(s.counts).length === 0;
      const invalidCounts = s.counts !== undefined && !emptyCounts && counts === null;
      const invalidRows = rawAlerts !== null && rawAlerts.length !== alerts.length;
      const inconsistent = counts !== null && ALERT_LEVELS.some((lv) => counts![lv] < salvagedCounts[lv]);
      const missingRows = counts !== null && ALERT_LEVELS.some((lv) => counts![lv] > salvagedCounts[lv]);
      if (invalidRows || inconsistent) counts = null;
      // Only an explicit, complete alert list can establish zero alerts.
      if (counts === null && rawAlerts !== null && !invalidRows && !invalidCounts && !inconsistent) {
        counts = salvagedCounts;
      }
      return {
        execution: execution === "completed" ? "completed" : undefined,
        reportStatus: reportStatus === "complete" ? "complete" : undefined,
        alerts,
        counts,
        salvagedCounts,
        partial: rawAlerts === null || invalidRows || invalidCounts || inconsistent || missingRows,
        target: typeof s.target === "string" ? s.target : null,
        source: parseCheckcifSource(s.source),
        checkedAt: typeof s.checked_at === "string" ? s.checked_at : null,
        note: typeof s.note === "string" ? s.note : null,
      };
    }
  } catch {
    /* head-truncated -> salvage below */
  }
  // 2. truncated: salvage the surviving tail alerts
  const alerts = salvageAlerts(tail);
  if (alerts.length === 0) return null;
  const salvagedCounts = countByLevel(alerts);
  let counts = tail.includes('"counts"')
    ? toCounts(safeParseAfter(tail, '"counts"'))
    : null;
  if (counts !== null && ALERT_LEVELS.some((lv) => counts![lv] < salvagedCounts[lv])) counts = null;
  return {
    alerts,
    counts,
    salvagedCounts,
    partial: true,
    target: rxStr(tail, "target"),
    source: parseCheckcifSource(safeParseAfter(tail, '"source"')),
    checkedAt: rxStr(tail, "checked_at"),
    note: rxStr(tail, "note"),
  };
}

/** Parse the object right after `"key":` (e.g. a counts dict), if intact. */
function safeParseAfter(tail: string, key: string): unknown {
  const at = tail.indexOf(key);
  if (at < 0) return null;
  const brace = tail.indexOf("{", at);
  if (brace < 0) return null;
  const slice = balancedSlice(tail, brace);
  if (slice === null) return null;
  try {
    return JSON.parse(slice);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------- thread lookup

export const CHECKCIF_TOOLS = new Set(["run_checkcif", "submit_iucr_checkcif"]);

export interface LatestCheckcif {
  item: ToolCardItem;
  /** null while running / on error / nothing salvageable. */
  data: CheckcifData | null;
}

/** Most recent checkCIF tool card in the transcript (running included). */
export function latestCheckcif(items: ChatItem[]): LatestCheckcif | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.type === "tool" && CHECKCIF_TOOLS.has(it.tool)) {
      const parsed = it.status === "running" ? null : parseCheckcifTail(it.resultTail);
      const data = it.status === "ok" || (parsed?.execution && parsed.execution !== "completed")
        ? parsed : null;
      return { item: it, data };
    }
  }
  return null;
}
