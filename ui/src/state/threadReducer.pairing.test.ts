/** Lifecycle pairing by codex item id (2026-09-16, "the tool card never
 * stops running"). Fixture: a real transcript slice (usertest test4-0909,
 * eids 2139-2156, outputs truncated) where three PowerShell commands ran
 * concurrently and finished in start order while the reducer paired every
 * completion with the NEWEST running card - so the first card kept spinning
 * with no output and the last completion produced a duplicate. */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import { zh } from "../lib/zh";
import { currentActionText } from "../lib/currentAction";
import fixture from "./__fixtures__/concurrent-commands.json";
import {
  initialThreadState,
  threadReducer,
  type ChatItem,
  type CommandCardItem,
  type ThreadState,
  type ToolCardItem,
} from "./threadReducer";

const T0 = 1700000000;
const start = { kind: "turn_started", ts: T0 } as WbEvent;
const real = (fixture as { events: WbEvent[] }).events;

function apply(events: WbEvent[], state = initialThreadState("t")): ThreadState {
  return events.reduce(
    (st, ev) => threadReducer(st, { type: "event", ev, seq: st.cursor + 1 }),
    state,
  );
}
const commands = (st: ThreadState) =>
  st.items.filter((it): it is CommandCardItem => it.type === "command");
const tools = (st: ThreadState) =>
  st.items.filter((it): it is ToolCardItem => it.type === "tool");

const tool = (kind: string, name: string, itemId: string | null, extra: Record<string, unknown> = {}) =>
  ({
    kind, ts: T0 + 1, server: "crystalpilot", tool: name, args: {}, status: "in_progress",
    ok: null, error: null, duration_ms: null, result_tail: null, item_id: itemId, ...extra,
  }) as WbEvent;
const cmd = (kind: string, itemId: string | null, extra: Record<string, unknown> = {}) =>
  ({
    kind, ts: T0 + 1, command: `cmd-${itemId ?? "legacy"}`, status: kind === "command_started" ? "in_progress" : "completed",
    exit_code: kind === "command_started" ? null : 0, output_tail: null,
    ...(itemId === null ? {} : { item_id: itemId }), ...extra,
  }) as WbEvent;

describe("real transcript: three concurrent commands", () => {
  it("every completion lands on the card that started it; nothing stays running, nothing is duplicated", () => {
    const st = apply([start, ...real]);
    const cards = commands(st);
    expect(cards).toHaveLength(3);
    expect(cards.map((c) => c.itemId)).toEqual([
      "call_qZ0YZ40SrLf6hjfW4gW1Ssns",
      "call_E3lPonYqWumBPjheUF6ouYVv",
      "call_AMq1wgfbYBgxFelsGmGDicuB",
    ]);
    expect(cards.every((c) => c.done && c.status === "completed" && c.exitCode === 0)).toBe(true);
    // the first Get-Content's output ("TITL 222 in P64 …") is on the FIRST
    // card, not on the rg card that started last
    expect(cards[0].output).toMatch(/^TITL 222/);
    expect(cards[1].output).toMatch(/^\s+-1\s+5\s+-20/);
    expect(cards[2].output).toMatch(/crystalpilot\\refine/);
    expect(st.openCommandIds).toEqual([]);
    expect(st.openCommandId).toBeNull();
    expect(cards.every((c) => c.raw.length === 2 && c.raw[0].kind === "command_started" && c.raw[1].kind === "command_completed")).toBe(true);
  });

  it("while the first command is still open, the status line names the most recent running one only", () => {
    const upToSecondStart = real.slice(0, real.findIndex((e) => e.kind === "command_started") + 4);
    const st = apply([start, ...upToSecondStart]);
    expect(commands(st).filter((c) => !c.done)).toHaveLength(2);
    expect(String(currentActionText(st.items, st.openToolIds))).toContain("读取文件");
  });

  it("a bootstrap replay of the same slice gives identical cards, and live replays of its eids are dropped", () => {
    const events = [{ ...start, eid: 2138 }, ...real] as WbEvent[];
    const live = apply(events);
    let replay = threadReducer(initialThreadState("t"), { type: "bootstrap", events, reset: true, busy: true });
    expect(commands(replay)).toEqual(commands(live));
    const before = replay.items.length;
    for (const ev of real) replay = threadReducer(replay, { type: "event", ev, seq: 900 });
    expect(replay.items.length).toBe(before);
    expect(commands(replay).every((c) => c.done)).toBe(true);
  });
});

describe("synthetic: out-of-order and missing terminals", () => {
  it("commands completing in reverse order still pair by id; output deltas follow the id", () => {
    let st = apply([start, cmd("command_started", "a"), cmd("command_started", "b")]);
    st = threadReducer(st, { type: "stream", commandDeltas: [{ itemId: "a", delta: "AAA" }, { itemId: "b", delta: "BBB" }] });
    st = apply([cmd("command_completed", "b", { output_tail: "BBB" }), cmd("command_completed", "a", { output_tail: "AAA" })], st);
    const [a, b] = commands(st);
    expect([a.itemId, b.itemId]).toEqual(["a", "b"]);
    expect(a.output).toBe("AAA");
    expect(b.output).toBe("BBB");
    expect(commands(st).every((c) => c.done)).toBe(true);
  });

  it("an id-less legacy completion still lands on the newest running command", () => {
    const st = apply([start, cmd("command_started", null), cmd("command_completed", null, { output_tail: "done" })]);
    expect(commands(st)).toHaveLength(1);
    expect(commands(st)[0].done).toBe(true);
    expect(commands(st)[0].output).toBe("done");
  });

  it("two identical tools in flight pair by item id even when the second finishes first", () => {
    const st = apply([
      start,
      tool("tool_started", "inspect_model", "m1"),
      tool("tool_started", "inspect_model", "m2"),
      tool("tool_completed", "inspect_model", "m2", { status: "completed", ok: true, result_tail: '{"ok":true,"summary":{"tag":"second"}}' }),
    ]);
    const [first, second] = tools(st);
    expect(first.status).toBe("running");
    expect(second.status).toBe("ok");
    expect(second.summary?.parsed).toMatchObject({ summary: { tag: "second" } });
    expect(st.openToolIds).toHaveLength(1);
  });

  it("tool progress is routed by item id, not to the newest card", () => {
    const st = apply([
      start,
      tool("tool_started", "run_shelxl", "s1"),
      tool("tool_started", "solvent_mask", "s2"),
      { kind: "tool_progress", ts: T0 + 2, message: "等待 SHELXL 作业 · 42 s", item_id: "s1" } as WbEvent,
    ]);
    const [shelxl, mask] = tools(st);
    expect(shelxl.progressLine).toBe("等待 SHELXL 作业 · 42 s");
    expect(mask.progressLine).toBeNull();
  });

  it("an id-less tool completion falls back to FIFO by name (old transcripts)", () => {
    const st = apply([
      start,
      tool("tool_started", "inspect_model", null),
      tool("tool_started", "inspect_model", null),
      tool("tool_completed", "inspect_model", null, { status: "completed", ok: true }),
    ]);
    expect(tools(st).map((t) => t.status)).toEqual(["ok", "running"]);
  });

  it("a normally completed turn marks a command that never reported back as 未收到结果, not 已中断 and not success", () => {
    const st = apply([
      start,
      cmd("command_started", "lost"),
      cmd("command_started", "fine"),
      cmd("command_completed", "fine"),
      { kind: "turn_completed", ts: T0 + 9, status: "completed", duration_ms: 9000 } as WbEvent,
    ]);
    const [lost, fine] = commands(st);
    expect(lost.done).toBe(true);
    expect(lost.status).toBe("no_result");
    expect(lost.exitCode).toBeNull();
    expect(fine.status).toBe("completed");
    expect(lost.raw.map((e) => e.kind)).toEqual(["command_started"]);
  });

  it("a tool without a terminal event: no_result at a completed turn, interrupted at a stopped or failed one", () => {
    const completed = apply([start, tool("tool_started", "refine", "r1"), { kind: "turn_completed", ts: T0 + 9, status: "completed", duration_ms: 1 } as WbEvent]);
    expect(tools(completed)[0].status).toBe("no_result");
    expect(tools(completed)[0].ok).toBeNull();
    const stopped = apply([start, tool("tool_started", "refine", "r1"), { kind: "turn_completed", ts: T0 + 9, status: "interrupted", duration_ms: 1 } as WbEvent]);
    expect(tools(stopped)[0].status).toBe("interrupted");
    const failed = apply([start, tool("tool_started", "refine", "r1"), { kind: "turn_failed", ts: T0 + 9, error: "gateway" } as WbEvent]);
    expect(tools(failed)[0].status).toBe("interrupted");
    // neither is a scientific success: the metrics cursor and crystal signal stay untouched
    for (const st of [completed, stopped, failed]) {
      expect(st.metricsCursor).toEqual({});
      expect(st.crystalSignal?.tool).not.toBe("refine");
    }
  });

  it("a new turn starting closes the previous turn's leftovers as no_result", () => {
    const st = apply([start, tool("tool_started", "refine", "r1"), { ...start, ts: T0 + 20 }]);
    expect(tools(st)[0].status).toBe("no_result");
    expect(currentActionText(st.items, st.openToolIds)).toBe(zh.stickyThinking);
  });

  it("a cut transcript (ends mid-turn, server says idle) closes its rows as no_result and the turn as inactive", () => {
    const events = [start, tool("tool_started", "run_shelxl", "x1"), cmd("command_started", "c1")] as WbEvent[];
    const stale = threadReducer(initialThreadState("t"), { type: "bootstrap", events, reset: true, busy: false });
    expect(stale.turn.active).toBe(false);
    expect(tools(stale)[0].status).toBe("no_result");
    expect(commands(stale)[0].status).toBe("no_result");
    // the same transcript while the server IS busy keeps the rows live
    const live = threadReducer(initialThreadState("t"), { type: "bootstrap", events, reset: true, busy: true });
    expect(live.turn.active).toBe(true);
    expect(tools(live)[0].status).toBe("running");
  });

  it("generic rows (file change, web search, image view) pair phases by item id", () => {
    const st = apply([
      start,
      { kind: "file_change_started", ts: T0 + 1, changes: null, status: "in_progress", item_id: "f1" } as WbEvent,
      { kind: "file_change_started", ts: T0 + 1, changes: null, status: "in_progress", item_id: "f2" } as WbEvent,
      { kind: "imageView_started", ts: T0 + 1, detail: { path: "a.png" }, item_id: "i1" } as WbEvent,
      { kind: "file_change_completed", ts: T0 + 2, changes: [{ path: "x" }], status: "completed", item_id: "f1" } as WbEvent,
      { kind: "imageView_completed", ts: T0 + 2, detail: { path: "a.png" }, item_id: "i1" } as WbEvent,
    ]);
    const generic = st.items.filter((it): it is Extract<ChatItem, { type: "generic" }> => it.type === "generic");
    expect(generic.map((g) => [g.itemId, g.done])).toEqual([["f1", true], ["f2", false], ["i1", true]]);
    expect(generic[2].family).toBe("imageView");
  });

  it("ping and channel_closed are transport events: the state does not change", () => {
    const base = apply([start, tool("tool_started", "refine", "r1")]);
    const pinged = threadReducer(base, { type: "event", ev: { kind: "ping", ts: T0 + 5 } as WbEvent, seq: 0 });
    expect(pinged).toBe(base);
    const closed = threadReducer(base, { type: "event", ev: { kind: "channel_closed", ts: T0 + 5 } as WbEvent, seq: 0 });
    expect(closed).toBe(base);
    expect(tools(closed)[0].status).toBe("running");
  });

  it("raw events are bounded and keep the newest", () => {
    const events: WbEvent[] = [start, cmd("command_started", "u")];
    for (let i = 0; i < 12; i += 1) events.push(cmd("command_updated", "u", { status: `step${i}` }));
    const st = apply(events);
    const card = commands(st)[0];
    expect(card.raw.length).toBeLessThanOrEqual(8);
    expect(card.raw.at(-1)).toMatchObject({ status: "step11" });
    expect(card.status).toBe("step11");
  });
});
