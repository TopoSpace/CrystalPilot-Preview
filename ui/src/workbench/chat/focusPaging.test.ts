/** Synthetic lifecycle events, folded by the real reducer. No scientific results. */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../../lib/wbTypes";
import { initialThreadState, threadReducer } from "../../state/threadReducer";
import { projectBlocks } from "./MessageList";

const tail: WbEvent[] = [
  { kind: "turn_started", ts: 20, eid: 5 },
  { kind: "reasoning_summary", ts: 21, eid: 6, text: "Focused current reasoning" },
  { kind: "tool_started", ts: 22, eid: 7, server: "crystalpilot", tool: "inspect_model", args: {}, status: "in_progress", duration_ms: null, ok: null, result_tail: null, error: null },
];
const earlier: WbEvent[] = [
  { kind: "turn_started", ts: 1, eid: 1 },
  { kind: "command_completed", ts: 2, eid: 2, command: "synthetic failed command", status: "failed", exit_code: 2, output_tail: "Historical failure must remain visible" },
  { kind: "agent_message", ts: 3, eid: 3, text: "Earlier reply" },
  { kind: "turn_completed", ts: 4, eid: 4, status: "completed", duration_ms: 3000 },
];

for (const legacy of [false, true]) {
  describe(legacy ? "legacy timestamp source identity" : "persistent transcript event identity", () => {
    it("does not bind focused i2 reasoning to the failed i2 command after prepend", () => {
      const events = (rows: WbEvent[]) => legacy ? rows.map(({ eid: _eid, ...event }) => event) : rows;
      const state = threadReducer(initialThreadState("synthetic-focus"), { type: "bootstrap", reset: true, events: events(tail) });
      const loading = threadReducer(state, { type: "page_loading", loading: true });
      const focused = projectBlocks(loading.items, true).find((b) => b.kind === "reasoning");
      if (!focused || focused.kind !== "reasoning") throw new Error("Missing reasoning fixture");
      const originalId = focused.items[0].id;
      const paged = threadReducer(loading, { type: "prepend", events: events(earlier), page: { oldestEid: 1, hasMore: false } });
      expect(paged.items.find((it) => it.id === originalId)?.type).toBe("command");
      const blocks = projectBlocks(paged.items, true, focused);
      const reasoning = blocks.find((b) => b.kind === "reasoning");
      if (!reasoning || reasoning.kind !== "reasoning") throw new Error("Focused source was lost");
      expect(reasoning.items[0].type).toBe("reasoning");
      expect(reasoning.items[0].text).toBe("Focused current reasoning");
      expect(reasoning.items[0].id).not.toBe(originalId);
      expect(blocks.some((b) => b.kind === "item" && b.item.type === "command" && b.item.exitCode === 2)).toBe(true);
    });
  });
}

it("keeps a streamed reply's authoritative source when a later prepend replays it", () => {
  let state = threadReducer(initialThreadState("synthetic-stream"), { type: "event", seq: 1, ev: tail[0] });
  state = threadReducer(state, { type: "stream", agentDelta: "Streaming reply" });
  const live = state.items.find(item => item.type === "agent");
  state = threadReducer(state, { type: "event", seq: 2, ev: { kind: "agent_message", ts: 21, eid: 6, text: "Authoritative reply" } });
  const focused = projectBlocks(state.items, true).find((b) => b.kind === "item" && b.item.type === "agent")!;
  expect(focused.kind === "item" && focused.item.eid).toBe(6);
  expect(focused.kind === "item" && focused.item.type === "agent" && focused.item.renderId).toBe(live?.type === "agent" ? live.renderId : undefined);
  const paged = threadReducer(state, { type: "prepend", events: earlier, page: { oldestEid: 1, hasMore: false } });
  const blocks = projectBlocks(paged.items, true, focused);
  expect(paged.items.find(item => item.type === "agent" && item.eid === 6)).toMatchObject({ renderId: live?.type === "agent" ? live.renderId : undefined });
  expect(blocks.some((b) => b.kind === "item" && b.item.type === "agent" && b.item.eid === 6 && b.item.text === "Authoritative reply")).toBe(true);
  expect(blocks.some((b) => b.kind === "item" && b.item.type === "command" && b.item.exitCode === 2)).toBe(true);
});

it("keeps unpersisted live and interrupted text when paging, without duplicating or reordering it", () => {
  let state = threadReducer(initialThreadState("playback-page"), { type: "bootstrap", reset: true, events: [tail[0]] });
  state = threadReducer(state, { type: "stream", agentDelta: "Live buffered text" });
  const live = state.items.find(item => item.type === "agent")!;
  state = threadReducer(state, { type: "event", seq: 1, ev: { kind: "user_steer", ts: 24, eid: 7, text: "Keep this visible" } });
  state = threadReducer(state, { type: "prepend", events: earlier, page: {} });
  state = threadReducer(state, { type: "stream", agentDelta: " and more" });
  expect(state.items.filter(item => item.type === "agent" && item.renderId)).toHaveLength(1);
  const current = state.items.find(item => item.type === "agent" && item.renderId);
  expect(current).toMatchObject({ text: "Live buffered text and more", renderId: live.type === "agent" ? live.renderId : undefined });
  expect(state.items.indexOf(current!)).toBeLessThan(state.items.findIndex(item => item.type === "user" && item.steer));
  state = threadReducer(state, { type: "event", seq: 2, ev: { kind: "turn_completed", ts: 25, eid: 8, status: "interrupted", duration_ms: 5000 } });
  state = threadReducer(state, { type: "prepend", events: [{ kind: "agent_message", ts: 0, eid: 0, text: "Oldest note" }], page: {} });
  expect(state.items.filter(item => item.type === "agent" && item.renderId)).toHaveLength(1);
  expect(state.items.find(item => item.type === "agent" && item.renderId)).toMatchObject({ text: "Live buffered text and more", streaming: false });
});

it("does not swallow rows inserted between a focused block's sources", () => {
  const state = threadReducer(initialThreadState("synthetic-insert"), { type: "bootstrap", reset: true, events: [tail[0], tail[1], { kind: "reasoning_summary", ts: 23, eid: 8, text: "Second reasoning" }] });
  const focused = projectBlocks(state.items, true).find((b) => b.kind === "reasoning")!;
  const after = threadReducer(state, { type: "bootstrap", reset: true, events: [tail[0], tail[1], { ...earlier[1], ts: 22, eid: 7 }, { kind: "reasoning_summary", ts: 23, eid: 8, text: "Second reasoning" }] });
  const blocks = projectBlocks(after.items, true, focused);
  expect(blocks.some((b) => b.kind === "item" && b.item.type === "command" && b.item.exitCode === 2)).toBe(true);
  expect(blocks.filter((b) => b.kind === "reasoning")).toHaveLength(2);
});

it("releases an absent focused source instead of casting a reused id to reasoning", () => {
  const before = threadReducer(initialThreadState("synthetic-focus"), { type: "bootstrap", reset: true, events: tail });
  const focused = projectBlocks(before.items, true).find((b) => b.kind === "reasoning")!;
  const after = threadReducer(before, { type: "bootstrap", reset: true, events: earlier });
  const blocks = projectBlocks(after.items, false, focused);
  expect(blocks.some((b) => b.kind === "reasoning")).toBe(false);
  expect(blocks.some((b) => b.kind === "item" && b.item.type === "command" && b.item.exitCode === 2)).toBe(true);
});
