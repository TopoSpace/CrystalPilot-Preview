/** The metrics cursor behind the turn digest ("R1 a→b") and the crystal
 * pane refresh signal, driven with the real event shapes (round-2 evidence
 * D20 / D21). */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import { CRYSTAL_MUTATING, initialThreadState, threadReducer, type ThreadState } from "./threadReducer";

let ts = 1000;
function toolEvents(tool: string, result: unknown, ok = true): WbEvent[] {
  const base = { server: "crystalpilot", tool, args: {}, error: null };
  return [
    {
      ...base,
      kind: "tool_started",
      ts: ts++,
      status: "in_progress",
      duration_ms: null,
      ok: null,
      result_tail: null,
    } as WbEvent,
    {
      ...base,
      kind: "tool_completed",
      ts: ts++,
      status: "completed",
      duration_ms: 1200,
      ok,
      result_tail: JSON.stringify(result),
    } as WbEvent,
  ];
}

function run(state: ThreadState, events: WbEvent[]): ThreadState {
  let st = state;
  let seq = st.cursor;
  for (const ev of events) {
    seq += 1;
    st = threadReducer(st, { type: "event", ev, seq });
  }
  return st;
}

const VALIDATE = {
  ok: true,
  summary: {
    n_alerts: 0,
    confidence: { score: 86.6, grade: "high", breakdown: { r1: -13.4, goof: 0.0, diff_map: 0.0, alerts: 0 } },
  },
};

describe("metrics cursor", () => {
  it("advances on refine and ignores validate_structure / compare_nodes", () => {
    let st = initialThreadState("t1");
    st = run(st, toolEvents("refine", { ok: true, summary: { node: "n0002", r1_strong: 0.2293, wr2: 0.6465, goof: 5.887 } }));
    expect(st.metricsCursor.r1).toBe(0.2293);

    st = run(st, toolEvents("validate_structure", VALIDATE));
    expect(st.metricsCursor.r1).toBe(0.2293);
    expect(st.metricsCursor.goof).toBe(5.887);

    // a read-only tool whose result carries a genuine-looking r1 still may
    // not move the cursor: it did not change the model
    st = run(
      st,
      toolEvents("compare_nodes", {
        ok: true,
        summary: { a: { metrics: { r1_strong: 0.5 } }, b: { metrics: { r1_strong: 0.4 } }, delta_b_minus_a: { r1_strong: -0.1 } },
      }),
    );
    expect(st.metricsCursor.r1).toBe(0.2293);

    st = run(st, toolEvents("run_shelxl", { ok: true, summary: { shelxl: { r1_strong: 0.0948, wr2: 0.3049, goof: 1.41 } } }));
    expect(st.metricsCursor.r1).toBe(0.0948);
    expect(st.metricsCursor.goof).toBe(1.41);
  });

  it("does not advance on a failed tool", () => {
    let st = initialThreadState("t2");
    st = run(st, toolEvents("refine", { ok: true, summary: { r1_strong: 0.2 } }));
    st = run(st, toolEvents("refine", { ok: false, summary: { r1_strong: 0.9 } }, false));
    expect(st.metricsCursor.r1).toBe(0.2);
  });
});

describe("crystal pane refresh signal", () => {
  it("fires for every model-changing tool, including model_disorder (D21)", () => {
    for (const tool of ["model_disorder", "set_twin", "change_space_group", "checkout"]) {
      expect(CRYSTAL_MUTATING.has(tool), tool).toBe(true);
      let st = initialThreadState(`t-${tool}`);
      st = run(st, toolEvents(tool, { ok: true, summary: { node: "n0010" } }));
      expect(st.crystalSignal?.tool, tool).toBe(tool);
    }
  });

  it("stays quiet for read-only tools", () => {
    let st = initialThreadState("t3");
    st = run(st, toolEvents("validate_structure", VALIDATE));
    expect(st.crystalSignal).toBeNull();
  });
});
