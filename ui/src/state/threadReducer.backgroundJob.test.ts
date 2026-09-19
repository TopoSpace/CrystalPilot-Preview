/** Detached solver jobs stay visible (2026-09-18 NU-1000 stall).
 *
 * Two real turns were stopped by the user while SHELXT was 13 minutes into
 * its silent, exhaustive space-group search: no card, no rail text, no row
 * said a solver was running, and both finished with a solution afterwards.
 * The service now mirrors the job files as `background_job` events; here
 * the reducer, the system row, the current-action line and the status rail
 * are checked against that event shape - including the turn-boundary rule
 * (the job's row is never "interrupted") and adoption in a later turn. */
import { describe, expect, it } from "vitest";
import { currentActionText } from "../lib/currentAction";
import { railAction } from "../lib/statusRail";
import type { WbEvent } from "../lib/wbTypes";
import { zh } from "../lib/zh";
import { systemText } from "../workbench/chat/GenericRow";
import { initialThreadState, threadReducer, type GenericItem, type ThreadState } from "./threadReducer";

const T0 = 1_789_721_172; // 2026-09-18 16:46:12 local, the real job's start
const JOB = "job_20260918_164612";

function run(events: WbEvent[], base?: ThreadState): ThreadState {
  let st = base ?? initialThreadState("t");
  st = threadReducer(st, { type: "channel", status: "live" });
  let seq = st.cursor;
  for (const ev of events) {
    seq += 1;
    st = threadReducer(st, { type: "event", ev, seq });
  }
  return st;
}

const bg = (transition: string, extra: Record<string, unknown> = {}): WbEvent =>
  ({
    kind: "background_job", tool: "run_shelxt", program: "SHELXT", job: JOB,
    transition, stage: "space-group search", running: true,
    elapsed_s: 120.0, started_at: "2026-09-18T16:46:12", started_at_epoch: T0,
    laue: "6/mmm", tries_done: 12, best_cfom: 0.737, passed_acceptance: true,
    phasing_finished: true, phasing_s: 34.82, n_space_groups: null,
    auto_a: true, exhaustive_search: true, search_elapsed_s: 85.2,
    search_reference: { n_jobs: 1, median_s: 775.0, max_s: 775.0 },
    has_solution: false, adopted_at: null, error: null,
    ts: T0 + 120, ...extra,
  }) as WbEvent;

const finished = (extra: Record<string, unknown> = {}): WbEvent =>
  bg("finished", {
    running: false, stage: "finished", elapsed_s: 862.6, has_solution: true,
    n_space_groups: 18, search_elapsed_s: 774.97, ts: T0 + 863, ...extra,
  });

const detachStart: WbEvent = {
  kind: "tool_started", server: "crystalpilot", tool: "run_shelxt",
  args: { detach: true, composition: "Zr18 C264 O96" }, status: "in_progress",
  duration_ms: null, ok: null, result_tail: null, error: null, ts: T0,
} as WbEvent;
const detachDone: WbEvent = {
  kind: "tool_completed", server: "crystalpilot", tool: "run_shelxt",
  args: { detach: true }, status: "completed", duration_ms: 15_000, ok: true,
  result_tail: JSON.stringify({ ok: true, summary: { job: JOB, detached: true, no_state_change: true } }),
  error: null, ts: T0 + 15,
} as WbEvent;
const adoptDone = (fromJob: string): WbEvent =>
  ({
    kind: "tool_completed", server: "crystalpilot", tool: "run_shelxt",
    args: { from_job: fromJob }, status: "completed", duration_ms: 4_000, ok: true,
    result_tail: JSON.stringify({ ok: true, summary: { adopted: true, node: "n0002", reused_job: fromJob } }),
    error: null, ts: T0 + 1000,
  }) as WbEvent;

const jobRows = (st: ThreadState) =>
  st.items.filter((it): it is GenericItem => it.type === "generic" && it.kind === "background_job");

describe("background_job events", () => {
  it("one system row per job, created on start and rewritten in place by heartbeats", () => {
    let st = run([
      { kind: "user_message", text: "求解", ts: T0 - 60 },
      { kind: "turn_started", ts: T0 - 60 },
      detachStart, detachDone,
      bg("started"),
    ]);
    expect(jobRows(st)).toHaveLength(1);
    const row = jobRows(st)[0];
    expect(row.family).toBe("system");
    expect(row.done).toBe(true);           // a turn boundary must not close it
    expect(row.phase).toBe("running");
    const text = systemText(row);
    expect(text).toContain("SHELXT 后台求解");
    expect(text).toContain(zh.bgStageSearch);
    expect(text).toContain("2 分");         // 120 s elapsed
    expect(text).toContain(zh.bgSilentExhaustive);
    expect(text).toContain(`${zh.bgRefPrefix} 12 分 55 秒`);
    expect(st.backgroundJobs[JOB].running).toBe(true);

    st = run([bg("heartbeat", { elapsed_s: 135.0, ts: T0 + 135 })], st);
    expect(jobRows(st)).toHaveLength(1);
    expect(st.backgroundJobs[JOB].elapsedS).toBe(135);
    expect(systemText(jobRows(st)[0])).toContain("2 分 15 秒");
  });

  it("the rail and the current action name the solver while the turn runs", () => {
    const st = run([
      { kind: "user_message", text: "求解", ts: T0 - 60 },
      { kind: "turn_started", ts: T0 - 60 },
      detachStart, detachDone,
      bg("started"),
      {
        kind: "command_started", command: "Start-Sleep -Seconds 30", status: "in_progress",
        exit_code: null, output_tail: null, item_id: "c1", ts: T0 + 121,
      } as WbEvent,
    ]);
    const a = railAction(st, (T0 + 130) * 1000);
    expect(a.kind).toBe("working");
    const text = String(a.text);
    expect(text).toContain("SHELXT 后台求解");
    expect(text).toContain(zh.bgStageSearch);
    // the local clock advances the server's elapsed value between heartbeats
    expect(text).toContain("2 分 10 秒");
    // without any live tool or command the solver line stands alone
    const alone = currentActionText([], [], st.backgroundJobs, (T0 + 130) * 1000);
    expect(String(alone).startsWith("SHELXT 后台求解")).toBe(true);
    expect(currentActionText([], [], {}, 0)).toBe(zh.stickyThinking);
  });

  it("a stopped turn does not silence a running solver", () => {
    const st = run([
      { kind: "user_message", text: "求解", ts: T0 - 60 },
      { kind: "turn_started", ts: T0 - 60 },
      detachStart, detachDone,
      bg("started"),
      { kind: "turn_completed", status: "interrupted", duration_ms: 375_000, ts: T0 + 315 } as WbEvent,
      bg("heartbeat", { elapsed_s: 330.0, ts: T0 + 330 }),
    ]);
    const row = jobRows(st)[0];
    expect(row.phase).toBe("running");    // not "interrupted"
    expect(st.backgroundJobs[JOB].running).toBe(true);
    const a = railAction(st, (T0 + 331) * 1000);
    expect(a.kind).toBe("background");
    expect(String(a.text)).toContain(zh.railBackgroundAfterTurn);
    expect(String(a.text)).toContain("SHELXT 后台求解");
    expect(a.elapsedMs).toBe(331_000);
    expect(a.muted).toBe(true);
  });

  it("finished but unadopted: the row asks for adoption and the rail says a solution waits", () => {
    const st = run([
      { kind: "user_message", text: "求解", ts: T0 - 60 },
      { kind: "turn_started", ts: T0 - 60 },
      bg("started"),
      { kind: "turn_completed", status: "interrupted", duration_ms: 375_000, ts: T0 + 315 } as WbEvent,
      finished(),
    ]);
    const row = jobRows(st)[0];
    expect(row.phase).toBe("completed");
    const text = systemText(row);
    expect(text).toContain(zh.bgStageFinished);
    expect(text).toContain("14 分 23 秒");
    expect(text).toContain("最佳 CFOM 0.737");
    expect(text).toContain("6/mmm 评估了 18 个空间群");
    expect(text).toContain(`run_shelxt(from_job='${JOB}')`);
    const a = railAction(st, (T0 + 900) * 1000);
    expect(a.kind).toBe("interrupted");
    expect(String(a.text)).toContain(zh.railSolutionReady);
  });

  it("adoption in a later turn closes the loop - by the tool result and by the server transition", () => {
    const base = run([
      { kind: "user_message", text: "求解", ts: T0 - 60 },
      { kind: "turn_started", ts: T0 - 60 },
      bg("started"),
      { kind: "turn_completed", status: "interrupted", duration_ms: 375_000, ts: T0 + 315 } as WbEvent,
      finished(),
    ]);
    // client side: run_shelxt(from_job=<path or name>) succeeded
    const byTool = run([
      { kind: "user_message", text: "采用", ts: T0 + 990 },
      { kind: "turn_started", ts: T0 + 990 },
      adoptDone(`H:\\proj\\.crystalpilot\\refine\\shelxt\\${JOB}`),
      { kind: "turn_completed", status: "completed", duration_ms: 4_000, ts: T0 + 1001 } as WbEvent,
    ], base);
    expect(byTool.backgroundJobs[JOB].adopted).toBe(true);
    expect(byTool.backgroundJobs[JOB].adoptedNode).toBe("n0002");
    const text = systemText(jobRows(byTool)[0]);
    expect(text).toContain(zh.bgAdopted);
    expect(text).toContain("节点 n0002");
    expect(text).not.toContain("尚未采用");
    const a = railAction(byTool, (T0 + 1100) * 1000);
    expect(a.kind).toBe("idle");
    expect(String(a.text)).not.toContain(zh.railSolutionReady);
    // server side: the registry's adopted_at arrives as a transition
    const byServer = run([finished({ transition: "adopted", adopted_at: "2026-09-18T17:30:00", ts: T0 + 2640 })], base);
    expect(byServer.backgroundJobs[JOB].adopted).toBe(true);
    expect(systemText(jobRows(byServer)[0])).toContain(zh.bgAdopted);
    expect(jobRows(byServer)).toHaveLength(1);
  });

  it("failure states are named, not dressed up", () => {
    const killed = run([bg("killed", { running: false, stage: "killed", elapsed_s: 1500, error: "shelxt hit the 600 s limit after 1500 s, but PHASING HAD ALREADY FINISHED", ts: T0 + 1500 })]);
    const text = systemText(jobRows(killed)[0]);
    expect(text).toContain(zh.bgStageKilled);
    expect(text).toContain("25 分");
    expect(text).toContain("shelxt hit the 600 s limit");
    expect(jobRows(killed)[0].phase).toBe("failed");
    const died = run([bg("died", { running: false, stage: "died", elapsed_s: 300, ts: T0 + 300 })]);
    expect(systemText(jobRows(died)[0])).toContain(zh.bgStageDied);
  });

  it("a transcript bootstrap with the live snapshot appended rebuilds the same single row", () => {
    const events = [
      { kind: "user_message", text: "求解", ts: T0 - 60, eid: 1 },
      { kind: "turn_started", ts: T0 - 60, eid: 2 },
      { ...bg("started"), eid: 3 },
      { ...bg("stage", { stage: "element assignment", elapsed_s: 810, ts: T0 + 810 }), eid: 4 },
      { kind: "turn_completed", status: "interrupted", duration_ms: 375_000, ts: T0 + 315, eid: 5 },
      // no eid: appended by the transcript route from the watcher's memory
      finished({ transition: "snapshot", ts: T0 + 900 }),
    ] as WbEvent[];
    const st = threadReducer(initialThreadState("boot"), { type: "bootstrap", events, reset: true, busy: false });
    expect(jobRows(st)).toHaveLength(1);
    expect(st.backgroundJobs[JOB].running).toBe(false);
    expect(st.backgroundJobs[JOB].hasSolution).toBe(true);
    expect(systemText(jobRows(st)[0])).toContain(zh.bgStageFinished);
    // the bootstrap closed nothing as "no result": the row is a system row
    expect(jobRows(st)[0].phase).toBe("completed");
  });
});
