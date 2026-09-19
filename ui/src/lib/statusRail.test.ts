/** Status rail model (round-3 R2-A): one action line derived from real
 * event shapes, stages as visited/current/pending. */
import { describe, expect, it } from "vitest";
import {
  initialThreadState,
  threadReducer,
  type ThreadState,
} from "../state/threadReducer";
import type { WbEvent } from "./wbTypes";
import { railAction, railModel, SHIMMER_MUTE_MS } from "./statusRail";

let ts = 1000;
function run(events: WbEvent[], base?: ThreadState): ThreadState {
  let st = base ?? initialThreadState("t");
  st = threadReducer(st, { type: "channel", status: "live" });
  let seq = st.cursor;
  for (const ev of events) {
    seq += 1;
    st = threadReducer(st, {
      type: "event",
      ev: { ...ev, ts: ev.ts || ts++ },
      seq,
    });
  }
  return st;
}

const toolStart = (tool: string): WbEvent =>
  ({
    kind: "tool_started",
    server: "crystalpilot",
    tool,
    args: {},
    status: "in_progress",
    duration_ms: null,
    ok: null,
    result_tail: null,
    error: null,
    ts: 0,
  }) as WbEvent;
const toolDone = (
  tool: string,
  result: unknown = { ok: true, summary: {} },
): WbEvent =>
  ({
    kind: "tool_completed",
    server: "crystalpilot",
    tool,
    args: {},
    status: "completed",
    duration_ms: 900,
    ok: true,
    result_tail: JSON.stringify(result),
    error: null,
    ts: 0,
  }) as WbEvent;
const toolFailed = (tool: string): WbEvent =>
  ({
    kind: "tool_completed",
    server: "crystalpilot",
    tool,
    args: {},
    status: "failed",
    duration_ms: 900,
    ok: false,
    result_tail: JSON.stringify({ ok: false }),
    error: "boom",
    ts: 0,
  }) as WbEvent;

describe("railAction", () => {
  it("a fresh thread says it has not started", () => {
    const st = run([]);
    expect(railAction(st, Date.now()).kind).toBe("fresh");
  });

  it("a live turn names the running tool, counts elapsed time and shimmers", () => {
    const startTs = 1_700_000_000;
    const st = run([
      { kind: "user_message", text: "go", ts: startTs },
      { kind: "turn_started", ts: startTs },
      toolStart("run_shelxl"),
    ]);
    const a = railAction(st, startTs * 1000 + 42_000);
    expect(a.kind).toBe("working");
    expect(String(a.text)).toContain("SHELXL");
    expect(a.elapsedMs).toBe(42_000);
    expect(a.muted).toBe(false);
  });

  it("after five minutes the shimmer is muted but the timer keeps going", () => {
    const startTs = 1_700_000_000;
    const st = run([
      { kind: "turn_started", ts: startTs },
      toolStart("run_shelxl"),
    ]);
    const a = railAction(st, startTs * 1000 + SHIMMER_MUTE_MS + 1000);
    expect(a.kind).toBe("working");
    expect(a.muted).toBe(true);
    expect(a.elapsedMs).toBe(SHIMMER_MUTE_MS + 1000);
  });

  it("a pending approval wins over the running tool", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("run_shelxl"),
      {
        kind: "approval_request",
        approval_id: "a1",
        method: "tool",
        detail: {},
        mcp_server: "crystalpilot",
        mcp_message:
          'Allow the crystalpilot MCP server to run tool "run_shelxl"?',
        mcp_tool_params: {},
        ts: 0,
      } as WbEvent,
    ]);
    const a = railAction(st, Date.now());
    expect(a.kind).toBe("approval");
  });

  it("idle summarises the last completed turn: duration and last node", () => {
    const st = run([
      { kind: "user_message", text: "go", ts: 0 },
      { kind: "turn_started", ts: 0 },
      toolStart("refine"),
      toolDone("refine", { ok: true, summary: { node: "n0007", r1: 0.05 } }),
      {
        kind: "turn_completed",
        status: "completed",
        duration_ms: 95_000,
        ts: 0,
      },
    ]);
    const a = railAction(st, Date.now());
    expect(a.kind).toBe("idle");
    expect(String(a.text)).toContain("01:35");
    expect(String(a.text)).toContain("n0007");
  });

  it("a failed or interrupted last turn says so", () => {
    const failed = run([
      { kind: "turn_started", ts: 0 },
      { kind: "turn_failed", error: "boom", ts: 0 } as WbEvent,
    ]);
    expect(railAction(failed, Date.now()).kind).toBe("failed");
    const stopped = run([
      { kind: "turn_started", ts: 0 },
      { kind: "turn_completed", status: "interrupted", duration_ms: 10, ts: 0 },
    ]);
    expect(railAction(stopped, Date.now()).kind).toBe("interrupted");
  });
});

describe("railModel stages", () => {
  it("an interrupted tool is visited, not still current after the turn ends", () => {
    let st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("run_shelxt"),
    ]);
    expect(railModel(st, Date.now()).stages.find((s) => s.id === "solve")?.state).toBe("current");
    st = run([{ kind: "turn_completed", status: "interrupted", duration_ms: 10, ts: 0 }], st);
    expect(railModel(st, Date.now()).stages.find((s) => s.id === "solve")?.state).toBe("visited");
    st = run([{ kind: "turn_started", ts: 0 }, toolStart("list_nodes")], st);
    expect(railModel(st, Date.now()).stages.find((s) => s.id === "solve")?.state).toBe("visited");
  });

  it("a failed turn cannot leave an uncompleted tool as the current stage", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("run_shelxl"),
      { kind: "turn_failed", error: "connection lost", ts: 0 } as WbEvent,
    ]);
    expect(railModel(st, Date.now()).stages.find((s) => s.id === "refine")?.state).toBe("visited");
  });

  it("marks observed stages as visited without implying completion", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("check_symmetry"),
      toolDone("check_symmetry"),
      toolStart("run_shelxt"),
      toolDone("run_shelxt"),
      toolStart("edit_atoms"),
      toolDone("edit_atoms"),
    ]);
    const m = railModel(st, Date.now());
    const by = Object.fromEntries(m.stages.map((s) => [s.id, s]));
    expect(by.data.state).toBe("pending");
    expect(by.symmetry.state).toBe("visited");
    expect(by.solve.state).toBe("visited");
    expect(by.model.state).toBe("current");
    expect(by.refine.state).toBe("pending");
    expect(by.model.nTools).toBe(1);
    expect(m.stages.map((s) => s.label)).toEqual([
      "数据",
      "定群",
      "求解",
      "建模",
      "精修",
      "验证",
      "交付",
    ]);
  });

  it("only get_geometry leaves every unobserved predecessor pending", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("get_geometry"),
      toolDone("get_geometry"),
    ]);
    const by = Object.fromEntries(railModel(st, Date.now()).stages.map((s) => [s.id, s.state]));
    expect(by.validate).toBe("current");
    expect(by.data).toBe("pending");
    expect(by.symmetry).toBe("pending");
    expect(by.solve).toBe("pending");
    expect(by.model).toBe("pending");
    expect(by.refine).toBe("pending");
  });

  it("direct CIF import does not imply data, symmetry or solve", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("import_cif_model"),
      toolDone("import_cif_model"),
    ]);
    const by = Object.fromEntries(railModel(st, Date.now()).stages.map((s) => [s.id, s.state]));
    expect(by.model).toBe("current");
    expect(by.data).toBe("pending");
    expect(by.symmetry).toBe("pending");
    expect(by.solve).toBe("pending");
  });

  it("shows a failed tool as visited while preserving the error action", () => {
    const st = run([
      { kind: "turn_started", ts: 0 },
      toolStart("run_shelxt"),
      toolFailed("run_shelxt"),
      { kind: "turn_failed", error: "boom", ts: 0 } as WbEvent,
    ]);
    const m = railModel(st, Date.now());
    const by = Object.fromEntries(m.stages.map((s) => [s.id, s]));
    expect(m.action.kind).toBe("failed");
    expect(by.solve.state).toBe("visited");
    expect(by.solve.nTools).toBe(0);
    expect(by.data.state).toBe("pending");
    expect(by.symmetry.state).toBe("pending");
  });
});
