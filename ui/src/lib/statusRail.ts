/** Status rail model (round-3 R2-A): the one place that says what the
 * thread is doing. Pure - the component only renders this.
 *
 * Left: stages as observed / current / pending. Observed is deliberately
 * neutral: a tool call is evidence of activity, not scientific completion.
 * Right: exactly one action line - working (humanized current tool +
 * elapsed + heartbeat), waiting for an approval, idle with the last turn's
 * summary, or the last turn's failure. After SHIMMER_MUTE_MS the shimmer
 * stops and only the timer moves: a user stops seeing a five-minute
 * animation, the number still says it is alive. */
import type { ReactNode } from "react";
import type { ChatItem, ThreadState } from "../state/threadReducer";
import { liveElapsedS, runningJobLine, runningJobs, unadoptedSolutions } from "./backgroundJobs";
import { currentActionText } from "./currentAction";
import { latestOpenAsk } from "./askCard";
import { fmtMmSs } from "./format";
import { stageState, stageTrack, type StageId, type StageState } from "./stages";
import { t } from "./i18n";

export const SHIMMER_MUTE_MS = 5 * 60 * 1000;

export type RailKind =
  | "connecting"
  | "fresh"
  | "working"
  | "approval"
  | "question"
  | "disconnected"
  | "compacting"
  | "idle"
  | "failed"
  | "interrupted"
  /** no turn is running but a detached solver still is (2026-09-18) */
  | "background";

export interface RailStage {
  id: StageId;
  label: string;
  state: StageState;
  nTools: number;
  /** turn ids that did this stage's work (navigation) */
  turnIds: string[];
}

export interface RailAction {
  kind: RailKind;
  text: ReactNode;
  /** milliseconds since the live turn started; null unless working */
  elapsedMs: number | null;
  /** shimmer switched off (long turn); the timer keeps counting */
  muted: boolean;
  /** last committed node id when idle, else null */
  node: string | null;
}

export interface RailModel {
  stages: RailStage[];
  action: RailAction;
  /** "situation_report" | "tool" | "" - what the stage reading rests on */
  basis: string;
}

function lastTurn(
  items: ChatItem[],
): Extract<ChatItem, { type: "turn" }> | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.type === "turn" && it.phase !== "started") return it;
  }
  return null;
}

function hasPendingApproval(items: ChatItem[]): boolean {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.type === "approval" && it.status === "pending") return true;
  }
  return false;
}

export function railAction(state: ThreadState, nowMs: number): RailAction {
  const items = state.items;
  if (state.channel === "connecting" && items.length === 0) {
    return {
      kind: "connecting",
      text: t.loading,
      elapsedMs: null,
      muted: false,
      node: null,
    };
  }
  if (state.channel === "dead" || state.channel === "reconnecting" || state.channel === "recovering") {
    return {
      kind: "disconnected",
      text: state.channel === "dead" ? t.channelDead : state.channel === "recovering" ? t.recovering : t.reconnecting,
      elapsedMs: null,
      muted: true,
      node: null,
    };
  }
  if (hasPendingApproval(items)) {
    return {
      kind: "approval",
      text: t.railApproval,
      elapsedMs: null,
      muted: false,
      node: null,
    };
  }
  if (!state.turn.active && latestOpenAsk(items)) {
    return {
      kind: "question",
      text: t.railQuestion,
      elapsedMs: null,
      muted: true,
      node: null,
    };
  }
  if (state.compacting) {
    return {
      kind: "compacting",
      text: t.railCompacting,
      elapsedMs: null,
      muted: false,
      node: null,
    };
  }
  if (state.turn.active) {
    const started = state.turn.startedTs;
    let elapsed: number | null = null;
    if (started !== null) {
      const startMs = started > 1e12 ? started : started * 1000;
      elapsed = Math.max(0, nowMs - startMs);
    }
    return {
      kind: "working",
      text: currentActionText(items, state.openToolIds, state.backgroundJobs, nowMs),
      elapsedMs: elapsed,
      muted: elapsed !== null && elapsed > SHIMMER_MUTE_MS,
      node: null,
    };
  }
  const turn = lastTurn(items);
  const bg = runningJobs(state.backgroundJobs);
  if (bg.length > 0) {
    // the turn ended (or was stopped) but SHELXT is still solving: say
    // so instead of "空闲" / "上次回合已中断" - that silence is what made
    // users stop a solver 13 minutes into its search
    const job = bg[bg.length - 1];
    const el = liveElapsedS(job, nowMs);
    return {
      kind: "background",
      text: `${runningJobLine(job, nowMs)} · ${t.railBackgroundAfterTurn}`,
      elapsedMs: el === null ? null : Math.round(el * 1000),
      muted: true,
      node: turn?.summary?.nodes.at(-1) ?? null,
    };
  }
  const waiting = unadoptedSolutions(state.backgroundJobs);
  if (turn === null) {
    return {
      kind: "fresh",
      text: t.railFresh,
      elapsedMs: null,
      muted: false,
      node: null,
    };
  }
  const node = turn.summary?.nodes.at(-1) ?? null;
  if (turn.phase === "failed" || turn.status === "failed") {
    return {
      kind: "failed",
      text: t.railFailed,
      elapsedMs: null,
      muted: false,
      node,
    };
  }
  if (turn.status === "interrupted") {
    return {
      kind: "interrupted",
      text: waiting.length > 0 ? `${t.railInterrupted} · ${t.railSolutionReady}` : t.railInterrupted,
      elapsedMs: null,
      muted: false,
      node,
    };
  }
  const parts: string[] = [t.railIdle];
  const d = fmtMmSs(turn.durationMs);
  if (d) parts.push(`${t.railLastTurn} ${d}`);
  if (node) parts.push(`${t.railNode} ${node}`);
  if (waiting.length > 0) parts.push(t.railSolutionReady);
  return {
    kind: "idle",
    text: parts.join(" · "),
    elapsedMs: null,
    muted: false,
    node,
  };
}

export function railModel(state: ThreadState, nowMs: number): RailModel {
  const info = stageTrack(state.items, state.turn.active ? state.openToolIds : []);
  const stages: RailStage[] = info.stages.map((s) => ({
    id: s.id,
    label: t.libs.stageNames[s.id],
    state: stageState(s.id, info.current, s.observed),
    nTools: s.nTools,
    turnIds: s.turns.map((t) => t.id),
  }));
  return { stages, action: railAction(state, nowMs), basis: info.basis ?? "" };
}
