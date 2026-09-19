/** Derive live header metrics + overview data from the event stream and report.
 *
 * While a run is in flight there is no report yet, so key numbers (space group,
 * latest R factors, confidence) are read from the newest relevant events; once
 * the report exists its values win.
 */
import type {
  Confidence,
  RunDetail,
  RunEvent,
  ValidationAlert,
} from "./api";
import { asNum, asStr } from "./format";

export interface HeaderMetrics {
  spaceGroup?: string;
  cell?: number[];
  r1?: number;
  wr2?: number;
  goof?: number;
  confidence?: { score: number; grade: string };
}

export function deriveMetrics(
  run: RunDetail | null,
  events: RunEvent[],
): HeaderMetrics {
  const m: HeaderMetrics = {};
  for (const ev of events) {
    const p = ev.payload;
    if (ev.kind === "stage_start" || ev.kind === "stage_end") {
      const cell = p.dataset?.unit_cell;
      if (Array.isArray(cell) && cell.length === 6) m.cell = cell.map(Number);
      const sg = asStr(p.space_group);
      if (sg) m.spaceGroup = sg;
    }
    if (ev.kind === "tool_result" && p.ok) {
      const s = p.summary ?? {};
      switch (p.tool) {
        case "refine":
          m.r1 = asNum(s.r1_strong) ?? m.r1;
          m.wr2 = asNum(s.wr2) ?? m.wr2;
          m.goof = asNum(s.goof) ?? m.goof;
          break;
        case "determine_space_group":
        case "set_space_group":
          m.spaceGroup = asStr(s.space_group) ?? m.spaceGroup;
          break;
        case "validate_structure": {
          const c = s.confidence as Record<string, unknown> | undefined;
          const score = asNum(c?.score);
          const grade = asStr(c?.grade);
          if (score !== undefined && grade) m.confidence = { score, grade };
          break;
        }
      }
    }
  }
  const rep = run?.report;
  if (rep) {
    m.spaceGroup = rep.symmetry?.space_group ?? m.spaceGroup;
    m.r1 = rep.refinement?.r1_strong ?? m.r1;
    m.wr2 = rep.refinement?.wr2 ?? m.wr2;
    m.goof = rep.refinement?.goof ?? m.goof;
    const c: Confidence | undefined = rep.validation?.confidence;
    if (c?.score !== undefined && c.grade) {
      m.confidence = { score: c.score, grade: c.grade };
    }
  }
  return m;
}

/** Validation alerts: report first, else the newest validate_structure result. */
export function deriveAlerts(
  run: RunDetail | null,
  events: RunEvent[],
): ValidationAlert[] | null {
  if (run?.report?.validation?.alerts) return run.report.validation.alerts;
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.kind === "tool_result" && ev.payload.tool === "validate_structure") {
      const alerts = ev.payload.summary?.alerts;
      if (Array.isArray(alerts)) return alerts as ValidationAlert[];
    }
  }
  return null;
}

export interface AgentFinish {
  status?: string;
  assessment?: string;
}

export function deriveAgentFinish(events: RunEvent[]): AgentFinish | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === "agent_finish") {
      const p = events[i].payload;
      return { status: asStr(p.status), assessment: asStr(p.assessment) };
    }
  }
  return null;
}

export interface TrajectoryInfo {
  snapshots: number;
  restores: number;
}

export function deriveTrajectory(events: RunEvent[]): TrajectoryInfo {
  let snapshots = 0;
  let restores = 0;
  for (const ev of events) {
    if (ev.kind === "tool_call") {
      if (ev.payload.tool === "snapshot_state") snapshots++;
      if (ev.payload.tool === "restore_state") restores++;
    }
  }
  return { snapshots, restores };
}
