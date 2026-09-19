/** Synthetic event fixtures test UI lifecycle only, not scientific outcomes. */
import { describe, expect, it } from "vitest";
import { currentActionText } from "../lib/currentAction";
import { railAction, railModel } from "../lib/statusRail";
import { humanizeTool } from "../lib/toolCards";
import type { WbEvent } from "../lib/wbTypes";
import { zh } from "../lib/zh";
import { initialThreadState, threadReducer, type ThreadState, type ToolCardItem } from "./threadReducer";

const start = { kind: "turn_started", ts: 1700000000 } as WbEvent;
const tool = (kind = "tool_started", name = "run_shelxl", extra = {}) => ({
  kind, ts: start.ts + 1, server: "crystalpilot", tool: name, args: {},
  status: "in_progress", ok: null, error: null, duration_ms: null, result_tail: null, ...extra,
}) as WbEvent;
const command = (id: string) => ({ kind: "command_started", ts: start.ts + 1, command: id, item_id: id, status: "in_progress", exit_code: null, output_tail: "synthetic partial output" }) as WbEvent;
const apply = (events: WbEvent[], state = initialThreadState("synthetic")): ThreadState => events.reduce(
  (st, ev) => threadReducer(st, { type: "event", ev, seq: st.cursor + 1 }), state,
);
const tools = (st: ThreadState) => st.items.filter((it): it is ToolCardItem => it.type === "tool");

// A turn that was stopped or failed interrupts its rows; a turn that ended
// normally (or a new turn / idle without a seen end) leaves rows whose
// result never arrived: "no_result". Neither is success.
for (const [terminal, closed] of [
  [{ kind: "turn_completed", status: "completed", duration_ms: 5000 }, "no_result"],
  [{ kind: "turn_completed", status: "interrupted", duration_ms: 5000 }, "interrupted"],
  [{ kind: "turn_failed", error: "synthetic transport failure" }, "interrupted"],
  [{ kind: "idle", artifacts: [] }, "no_result"],
  [{ kind: "turn_started" }, "no_result"],
] as const) {
  it(`synthetic ${terminal.kind}/${"status" in terminal ? terminal.status : ""} closes all open rows as ${closed}, never success`, () => {
    const initial = apply([start, tool(), tool("tool_started", "inspect_model"), command("one"), command("two")]);
    const st = apply([{ ...terminal, ts: start.ts + 5 } as WbEvent], initial);
    expect(tools(initial).every((it) => it.status === "running")).toBe(true);
    expect(tools(st).every((it) => it.status === closed && it.ok === null && it.progressLine === null)).toBe(true);
    expect(tools(st).every((it) => it.rawStatus === "in_progress" && it.durationMs === 4000)).toBe(true);
    expect(st.items.filter((it) => it.type === "command").every((it) => it.type === "command" && it.done && it.status === closed && it.exitCode === null)).toBe(true);
    expect(st.openToolIds).toEqual([]);
    expect(st.openCommandId).toBeNull();
    // A turn-end refresh is allowed; it is not a tool success or node commit.
    expect(st.crystalSignal?.tool).not.toBe("run_shelxl");
    expect(st.crystalSignal?.node).toBeUndefined();
    expect(st.metricsCursor).toEqual({});
    expect(currentActionText(st.items, st.openToolIds)).toBe(zh.stickyThinking);
    expect(railModel(st, Date.now()).stages.find((s) => s.id === "refine")?.state).toBe("visited");
    expect(humanizeTool(tools(st)[0])).toMatchObject({ warn: closed === "no_result" ? zh.toolNoResult : zh.toolInterrupted, chips: [], body: null });
  });
}

describe("synthetic completion boundaries", () => {
  it("keeps real completion/failure evidence while interrupting only unfinished rows", () => {
    const st = apply([start, tool(), tool("tool_started", "inspect_model"), tool("tool_completed", "inspect_model", { status: "failed", ok: false, error: "synthetic failure" }), { kind: "turn_failed", ts: start.ts + 10, error: "stopped" } as WbEvent]);
    expect(tools(st).map((it) => it.status)).toEqual(["interrupted", "error"]);
    expect(tools(st)[1].error).toBe("synthetic failure");
  });

  it("pairs an orphan update with its eventual completion", () => {
    const st = apply([start, tool("tool_updated"), tool("tool_completed", "run_shelxl", { status: "completed", ok: true })]);
    expect(tools(st)).toHaveLength(1);
    expect(tools(st)[0].status).toBe("ok");
    expect(st.openToolIds).toEqual([]);
  });

  it.each(["cancelled", "canceled", "interrupted", "aborted", "stopped"])("does not promote %s to tool or scientific success", (status) => {
    const st = apply([start, tool(), tool("tool_completed", "run_shelxl", { status, ok: null, result_tail: JSON.stringify({ summary: { r1: 0.1, node: "synthetic-not-committed" } }) })]);
    expect(tools(st)[0].status).toBe("interrupted");
    expect(st.metricsCursor).toEqual({});
    expect(st.crystalSignal).toBeNull();
  });

  it("replaying the same terminal transcript gives the same interrupted rows", () => {
    const events = [start, tool(), { kind: "turn_completed", ts: start.ts + 9, status: "interrupted", duration_ms: 9000 } as WbEvent];
    const live = apply(events);
    const replay = threadReducer(initialThreadState("synthetic"), { type: "bootstrap", events, reset: true });
    expect(tools(replay)).toEqual(tools(live));
  });

  it("a new turn cannot pick a previous generic action", () => {
    const st = apply([start, { kind: "webSearch_started", ts: start.ts + 1, detail: {} } as WbEvent, { ...start, ts: start.ts + 10 }]);
    expect(currentActionText(st.items)).toBe(zh.stickyThinking);
  });

  it("finds live tools beyond a long reasoning run", () => {
    const st = apply([start, tool(), ...Array.from({ length: 65 }, (_, i) => ({ kind: "reasoning_summary", ts: start.ts + 2 + i, text: "synthetic reasoning" }) as WbEvent)]);
    expect(String(currentActionText(st.items, st.openToolIds))).toContain("SHELXL");
  });

  it.each(["dead", "reconnecting", "recovering"] as const)("%s overrides a stale working line", (channel) => {
    const st = { ...apply([start, tool()]), channel };
    expect(railAction(st, Date.now())).toMatchObject({ kind: "disconnected", elapsedMs: null, muted: true });
  });

  it("distinguishes a pending question from idle", () => {
    const st = apply([{ kind: "agent_message", ts: start.ts, text: '```ask\n{"question":"synthetic question"}\n```' } as WbEvent]);
    expect(railAction(st, Date.now()).kind).toBe("question");
  });
});
