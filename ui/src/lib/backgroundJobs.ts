/** Detached solver jobs (run_shelxt detach=true) as the UI sees them.
 *
 * 2026-09-18: two NU-1000 turns were stopped by the user while SHELXT was
 * 13 minutes into its silent space-group search - nothing in the workbench
 * showed a solver running, and both finished with a solution afterwards.
 * The service now mirrors the job files as `background_job` events; this
 * module turns them into one line of Chinese for the system row, the
 * status rail and the current-action text, so all three say the same
 * thing. Pure functions only. */
import type { BackgroundJobEvent } from "./wbTypes";
import { t } from "./i18n";

export interface SearchReference {
  nJobs: number;
  medianS: number;
  maxS: number;
}

export interface BackgroundJobInfo {
  job: string;
  program: string;
  stage: string;
  running: boolean;
  /** seconds since the process started, as of `ts` */
  elapsedS: number | null;
  startedAtEpoch: number | null;
  laue: string | null;
  triesDone: number | null;
  bestCfom: number | null;
  phasingFinished: boolean;
  nSpaceGroups: number | null;
  searchElapsedS: number | null;
  searchRef: SearchReference | null;
  /** SHELXT evaluates every group of the Laue class (-a, heavy atom) */
  exhaustive: boolean;
  hasSolution: boolean;
  adopted: boolean;
  adoptedNode: string | null;
  error: string | null;
  transition: string;
  /** event time (seconds) the elapsed value refers to */
  ts: number;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function jobInfoFromEvent(
  ev: BackgroundJobEvent,
  prev?: BackgroundJobInfo | null,
): BackgroundJobInfo {
  const ref = ev.search_reference;
  const searchRef: SearchReference | null =
    ref && typeof ref === "object" && num(ref.median_s) !== null
      ? { nJobs: num(ref.n_jobs) ?? 0, medianS: num(ref.median_s) ?? 0, maxS: num(ref.max_s) ?? 0 }
      : null;
  return {
    job: ev.job,
    program: typeof ev.program === "string" && ev.program ? ev.program : "SHELXT",
    stage: typeof ev.stage === "string" ? ev.stage : "",
    running: ev.running === true,
    elapsedS: num(ev.elapsed_s),
    startedAtEpoch: num(ev.started_at_epoch),
    laue: typeof ev.laue === "string" ? ev.laue : null,
    triesDone: num(ev.tries_done),
    bestCfom: num(ev.best_cfom),
    phasingFinished: ev.phasing_finished === true,
    nSpaceGroups: num(ev.n_space_groups),
    searchElapsedS: num(ev.search_elapsed_s),
    searchRef,
    exhaustive: ev.exhaustive_search === true || ev.auto_a === true,
    hasSolution: ev.has_solution === true,
    adopted: Boolean(ev.adopted_at) || prev?.adopted === true,
    adoptedNode: prev?.adoptedNode ?? null,
    error: typeof ev.error === "string" && ev.error ? ev.error : null,
    transition: typeof ev.transition === "string" ? ev.transition : "",
    ts: ev.ts,
  };
}

/** "N 分 S 秒" / "S 秒" for a duration in seconds. */
export function fmtDurationZh(s: number | null): string {
  if (s === null || !Number.isFinite(s)) return "";
  const total = Math.max(0, Math.round(s));
  const m = Math.floor(total / 60);
  const sec = total % 60;
  if (m === 0) return `${sec} ${t.bgSecondsUnit}`;
  return sec === 0 ? `${m} ${t.bgMinutesUnit}` : `${m} ${t.bgMinutesUnit} ${sec} ${t.bgSecondsUnit}`;
}

export function stageLabelZh(stage: string): string {
  switch (stage) {
    case "starting":
      return t.bgStageStarting;
    case "phasing":
      return t.bgStagePhasing;
    case "phasing (grace)":
      return t.bgStagePhasingGrace;
    case "space-group search":
      return t.bgStageSearch;
    case "element assignment":
      return t.bgStageAssign;
    case "finished":
      return t.bgStageFinished;
    case "killed":
      return t.bgStageKilled;
    case "failed":
      return t.bgStageFailed;
    case "died":
      return t.bgStageDied;
    default:
      return stage;
  }
}

/** Live elapsed seconds: the server's value advanced by the local clock
 * since the event (so the rail's counter keeps moving between heartbeats). */
export function liveElapsedS(info: BackgroundJobInfo, nowMs?: number): number | null {
  if (!info.running) return info.elapsedS;
  if (nowMs !== undefined && info.startedAtEpoch !== null) {
    return Math.max(0, nowMs / 1000 - info.startedAtEpoch);
  }
  if (info.elapsedS === null) return null;
  if (nowMs === undefined) return info.elapsedS;
  const evMs = info.ts > 1e12 ? info.ts : info.ts * 1000;
  return Math.max(info.elapsedS, info.elapsedS + (nowMs - evMs) / 1000);
}

/** The one-line summary for a running job: "SHELXT 后台求解 · 空间群搜索
 * · 已 5 分 12 秒（此阶段 SHELXT 不输出；本项目先前同类搜索约 13 分）". */
export function runningJobLine(info: BackgroundJobInfo, nowMs?: number): string {
  const parts: string[] = [`${info.program} ${t.bgProgramSuffix}`, stageLabelZh(info.stage)];
  const el = liveElapsedS(info, nowMs);
  if (el !== null) parts.push(`${t.bgElapsedPrefix} ${fmtDurationZh(el)}`);
  const notes: string[] = [];
  if (info.stage === "space-group search") {
    notes.push(info.exhaustive ? t.bgSilentExhaustive : t.bgSilentSearch);
    if (info.searchRef) notes.push(`${t.bgRefPrefix} ${fmtDurationZh(info.searchRef.medianS)}`);
  } else if (info.stage === "phasing" || info.stage === "phasing (grace)") {
    if (info.triesDone !== null && info.triesDone > 0) {
      notes.push(`${info.triesDone} ${t.bgTriesUnit}${info.bestCfom !== null ? `${t.libs.sepComma}${t.bgBestCfom} ${info.bestCfom.toFixed(3)}` : ""}`);
    }
  }
  return notes.length > 0 ? `${parts.join(" · ")}${t.libs.parens(notes.join(t.libs.sepClause))}` : parts.join(" · ");
}

/** The system row text for any state of a job. */
export function jobRowText(info: BackgroundJobInfo, nowMs?: number): string {
  if (info.running) return runningJobLine(info, nowMs);
  const head = `${info.program} ${t.bgProgramSuffix}`;
  const took = info.elapsedS !== null ? `${t.bgTookPrefix} ${fmtDurationZh(info.elapsedS)}` : "";
  if (info.stage === "finished" && info.hasSolution) {
    const facts: string[] = [];
    if (took) facts.push(took);
    if (info.bestCfom !== null) facts.push(`${t.bgBestCfom} ${info.bestCfom.toFixed(3)}`);
    if (info.nSpaceGroups !== null && info.laue) facts.push(`${info.laue} ${t.bgGroupsEvaluated(info.nSpaceGroups)}`);
    const base = `${head} ${t.bgStageFinished}${facts.length > 0 ? t.libs.parens(facts.join(t.libs.sepComma)) : ""}`;
    if (info.adopted) {
      return `${base} · ${t.bgAdopted}${info.adoptedNode ? ` → ${t.bgAdoptedNode} ${info.adoptedNode}` : ""}`;
    }
    return `${base} · ${t.bgSolutionUnadopted(info.job)}`;
  }
  const label = stageLabelZh(info.stage === "finished" ? "failed" : info.stage);
  const tail = info.error ? ` · ${info.error.slice(0, 160)}` : "";
  return `${head} ${label}${took ? t.libs.parens(took) : ""}${tail}`;
}

export function runningJobs(jobs: Readonly<Record<string, BackgroundJobInfo>>): BackgroundJobInfo[] {
  return Object.values(jobs).filter((j) => j.running).sort((a, b) => a.ts - b.ts);
}

/** Finished solutions nobody adopted yet, newest first. */
export function unadoptedSolutions(jobs: Readonly<Record<string, BackgroundJobInfo>>): BackgroundJobInfo[] {
  return Object.values(jobs)
    .filter((j) => !j.running && j.hasSolution && !j.adopted && !j.error)
    .sort((a, b) => b.ts - a.ts);
}

/** The job name a run_shelxt(from_job=...) argument refers to (basename). */
export function jobNameFromArg(v: unknown): string | null {
  if (typeof v !== "string" || !v.trim()) return null;
  const parts = v.trim().split(/[\\/]/);
  const last = parts[parts.length - 1];
  return last || null;
}
