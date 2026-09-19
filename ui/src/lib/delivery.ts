/** Delivery card data (round-3 R2-A): what a delivery is, in four facts and
 * four files, instead of a wall of every path under the results folder. */
import type { ArtifactEntry, DeliveryMark } from "./wbTypes";
import { zh } from "./zh";

/** The files a reader opens first, in this order: the hand-over set the
 * group continues from by hand (res / cif / ins / hkl / p4p, + fab for a
 * masked model - usertest 2026-09-08), then the narrative. */
export const MAIN_FILES = [
  "final.cif",
  "final.fcf",
  "final.res",
  "final.ins",
  "final.hkl",
  "final.p4p",
  "final.fab",
  "SUMMARY.md",
  "VALIDATION.md",
] as const;

export interface DeliveryMetrics {
  r1: number | null;
  wr2: number | null;
  goof: number | null;
}

/** Can a person continue from the directory (write_outputs /
 * finalize_delivery `manual_continuation`)? */
export interface DeliveryHandover {
  ready: boolean;
  missing: string[];
  notes: string[];
}

export interface DeliveryFacts {
  status: string | null;
  waived: number;
  node: string | null;
  metrics: DeliveryMetrics | null;
  /** file names the finalize/write tool reported (basename only) */
  files: string[];
  outputDir: string | null;
  /** "shelxl-acta" (esds, geometry tables) or "model" (coordinates +
   * the statistics measured for this exact model) - what final.cif IS */
  cifGrade: string | null;
  handover: DeliveryHandover | null;
}

export function cifGradeLabel(grade: string | null): string {
  switch (grade) {
    case "shelxl-acta":
      return zh.deliveryCifGradeActa;
    case "model":
      return zh.deliveryCifGradeModel;
    default:
      return grade ?? "";
  }
}

export function normPath(p: string): string {
  return p.replace(/\\/g, "/");
}

/** Run logs are artifacts, not deliverables: keep them off the card. */
export function isDeliverable(rel: string): boolean {
  const r = normPath(rel);
  if (r.startsWith("command_output/") || r.includes("/command_output/"))
    return false;
  const base = r.split("/").pop() ?? r;
  if (base === "transcript.jsonl") return false;
  if (base.endsWith(".tmp") || /\.tmp\d/.test(base)) return false;
  return true;
}

export function deliveryArtifacts(
  artifacts: ReadonlyArray<ArtifactEntry>,
): ArtifactEntry[] {
  return artifacts.filter((a) => isDeliverable(a.rel));
}

/** Main files present, in MAIN_FILES order, each with its artifact when known. */
export function mainFiles(
  files: ReadonlyArray<string>,
  artifacts: ReadonlyArray<ArtifactEntry>,
): Array<{ name: string; artifact: ArtifactEntry | null }> {
  const present = new Set(files.map((f) => normPath(f).split("/").pop() ?? f));
  const out: Array<{ name: string; artifact: ArtifactEntry | null }> = [];
  for (const name of MAIN_FILES) {
    const art =
      artifacts.find(
        (a) => (normPath(a.rel).split("/").pop() ?? "") === name,
      ) ?? null;
    if (present.has(name) || art !== null) out.push({ name, artifact: art });
  }
  return out;
}

export function deliveryStatusLabel(status: string | null): string {
  switch (status) {
    case "final":
      return zh.deliveryStatusFinal;
    case "provisional":
      return zh.deliveryStatusProvisional;
    case "diagnostic":
      return zh.deliveryStatusDiagnostic;
    default:
      return status ?? "";
  }
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** Facts from the write_outputs / finalize_delivery result payloads
 * (parsed.summary). Either may be missing; finalize wins on status. */
export function deliveryFacts(
  writeParsed: unknown,
  finParsed: unknown,
): DeliveryFacts {
  const w =
    isObj(writeParsed) && isObj(writeParsed.summary) ? writeParsed.summary : {};
  const f =
    isObj(finParsed) && isObj(finParsed.summary) ? finParsed.summary : {};
  const status =
    (typeof f.status === "string" && f.status) ||
    (typeof w.status === "string" && w.status) ||
    null;
  const waived = Array.isArray(f.waived) ? f.waived.length : 0;
  const node =
    (typeof w.final_node === "string" && w.final_node) ||
    (isObj(w.source_state) && typeof w.source_state.node === "string"
      ? w.source_state.node
      : null);
  const m = isObj(w.metrics) ? w.metrics : null;
  const metrics = m
    ? { r1: num(m.r1_strong) ?? num(m.r1), wr2: num(m.wr2), goof: num(m.goof) }
    : null;
  const files = (
    Array.isArray(f.files) && f.files.length > 0
      ? f.files
      : Array.isArray(w.files)
        ? w.files
        : []
  ).filter((x): x is string => typeof x === "string");
  const outputDir =
    (typeof f.output_dir === "string" && f.output_dir) ||
    (typeof w.output_dir === "string" && w.output_dir) ||
    null;
  const cifGrade =
    (typeof f.cif_grade === "string" && f.cif_grade) ||
    (typeof w.cif_grade === "string" && w.cif_grade) ||
    null;
  const mc = isObj(f.manual_continuation)
    ? f.manual_continuation
    : isObj(w.manual_continuation)
      ? w.manual_continuation
      : null;
  const strs = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const handover: DeliveryHandover | null = mc
    ? { ready: mc.ready === true, missing: strs(mc.missing), notes: strs(mc.notes) }
    : null;
  return { status, waived, node, metrics, files, outputDir, cifGrade, handover };
}

/** Chip tone for a delivery status: 定稿 reads as done, 暂定 as the
 * accent, 诊断性 stays quiet. Shared by the node tree and the artifacts tab. */
export function deliveryTone(status: string | null): string {
  switch (status) {
    case "final":
      return "bg-ok/10 text-ok";
    case "provisional":
      return "bg-accent/10 text-accent";
    default:
      return "bg-raised text-ink-3";
  }
}

// ------------------------------------------------------- artifacts grouping

export interface ArtifactGroup {
  /** directory under the thread's results dir ("" = the top-level delivery) */
  dir: string;
  /** MAIN_FILES present, in that order */
  main: ArtifactEntry[];
  /** everything else deliverable, by name */
  rest: ArtifactEntry[];
}

export function baseName(rel: string): string {
  const r = normPath(rel);
  return r.split("/").pop() ?? r;
}

/** Artifacts by delivery directory (round-3 R2-B): the top-level delivery
 * first, sub-deliveries (guest-location-update, whole-guest-study, ...)
 * after it by name, run logs apart. Within a group the main files lead. */
export function groupArtifacts(artifacts: ReadonlyArray<ArtifactEntry>): {
  groups: ArtifactGroup[];
  logs: ArtifactEntry[];
} {
  const logs = artifacts.filter((a) => !isDeliverable(a.rel));
  const byDir = new Map<string, ArtifactEntry[]>();
  for (const a of artifacts) {
    if (!isDeliverable(a.rel)) continue;
    const r = normPath(a.rel);
    const i = r.lastIndexOf("/");
    const dir = i === -1 ? "" : r.slice(0, i);
    const list = byDir.get(dir) ?? [];
    list.push(a);
    byDir.set(dir, list);
  }
  const order = (a: string, b: string): number =>
    a === "" ? -1 : b === "" ? 1 : a.localeCompare(b);
  const mainRank = (a: ArtifactEntry): number => {
    const i = (MAIN_FILES as readonly string[]).indexOf(baseName(a.rel));
    return i === -1 ? MAIN_FILES.length : i;
  };
  const groups = [...byDir.entries()]
    .sort(([a], [b]) => order(a, b))
    .map(([dir, files]) => ({
      dir,
      main: files.filter((a) => mainRank(a) < MAIN_FILES.length).sort((a, b) => mainRank(a) - mainRank(b)),
      rest: files
        .filter((a) => mainRank(a) === MAIN_FILES.length)
        .sort((a, b) => baseName(a.rel).localeCompare(baseName(b.rel))),
    }));
  return { groups, logs };
}

/** The thread's results directory name (task_<stamp>), recovered from an
 * artifact's absolute path minus its rel; null when the two disagree. */
export function taskDirOf(a: ArtifactEntry): string | null {
  const p = normPath(a.path);
  const r = normPath(a.rel);
  if (!p.endsWith(`/${r}`)) return null;
  const base = p.slice(0, p.length - r.length - 1);
  return base.split("/").pop() || null;
}

/** The delivery manifest (node + status) behind an artifact group, matched
 * by results-relative directory. */
export function markFor(group: ArtifactGroup, marks: ReadonlyArray<DeliveryMark>): DeliveryMark | null {
  const sample = group.main[0] ?? group.rest[0];
  if (!sample) return null;
  const task = taskDirOf(sample);
  if (task === null) return null;
  const want = group.dir === "" ? task : `${task}/${group.dir}`;
  return marks.find((m) => normPath(m.rel) === want) ?? null;
}
