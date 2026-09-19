/** Event identity, transcript paging and command output (round-3 R1),
 * driven by the 2026-09-05 forensic captures: 83 native transcript lines +
 * the 2 SSE events that reproduced the "ghost running branch card", and the
 * 5 human inputs as both their SSE and transcript forms. */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import ghostJson from "./__fixtures__/minimal-ghost-card.json";
import humansJson from "./__fixtures__/human-inputs.json";
import {
  initialThreadState,
  threadReducer,
  type ThreadState,
} from "./threadReducer";

interface Captured {
  bootstrap: WbEvent[];
  events: Array<{ seq: number; event: WbEvent }>;
}

const FIXTURES: Record<string, unknown> = {
  "minimal-ghost-card.json": ghostJson,
  "human-inputs.json": humansJson,
};

function load<T>(name: string): T {
  return FIXTURES[name] as T;
}

function withEids(events: WbEvent[], start = 1): WbEvent[] {
  return events.map((e, i) => ({ ...e, eid: start + i }));
}

function bootstrap(
  events: WbEvent[],
  extra: Record<string, unknown> = {},
): ThreadState {
  return threadReducer(initialThreadState("t"), {
    type: "bootstrap",
    events,
    reset: true,
    ...extra,
  });
}

function apply(state: ThreadState, ev: WbEvent, seq = 0): ThreadState {
  return threadReducer(state, { type: "event", ev, seq });
}

const tools = (st: ThreadState, tool: string) =>
  st.items.filter((it) => it.type === "tool" && it.tool === tool);
const running = (st: ThreadState) =>
  st.items.filter((it) => it.type === "tool" && it.status === "running");
const users = (st: ThreadState) => st.items.filter((it) => it.type === "user");

describe("event identity (forensic ghost card)", () => {
  const ghost = load<Captured>("minimal-ghost-card.json");
  const twinIndex = (ev: WbEvent): number =>
    ghost.bootstrap.findIndex(
      (b) =>
        b.kind === ev.kind &&
        b.ts === ev.ts &&
        (b as { tool?: string }).tool === (ev as { tool?: string }).tool,
    );

  it("the captured SSE replays are transcript lines 1 and 4, outside the old 80-line window", () => {
    expect(ghost.bootstrap).toHaveLength(83);
    expect(ghost.events.map((e) => twinIndex(e.event))).toEqual([0, 3]);
  });

  it("without identity the replay still fabricates a second, running branch card (the bug)", () => {
    let st = bootstrap(ghost.bootstrap);
    for (const e of ghost.events) st = apply(st, e.event, e.seq);
    expect(tools(st, "branch")).toHaveLength(2);
    expect(running(st)).toHaveLength(1);
  });

  it("with eids the replay is dropped exactly: one branch card, nothing running, no new items", () => {
    const native = withEids(ghost.bootstrap);
    const base = bootstrap(native);
    let st = base;
    for (const e of ghost.events) {
      const eid = twinIndex(e.event) + 1;
      st = apply(st, { ...e.event, eid }, e.seq);
    }
    expect(st.items).toHaveLength(base.items.length);
    expect(tools(st, "branch")).toHaveLength(1);
    expect(running(st)).toHaveLength(0);
    expect(st.maxEid).toBe(83);
    expect(st.rawEvents).toHaveLength(83);
  });
});

describe("event identity (the five human inputs)", () => {
  const humans =
    load<Array<{ source: "sse" | "transcript"; event: WbEvent }>>(
      "human-inputs.json",
    );
  const transcript = humans
    .filter((h) => h.source === "transcript")
    .map((h) => h.event);
  const sse = humans.filter((h) => h.source === "sse").map((h) => h.event);

  it("all five survive a bootstrap, the steer included", () => {
    const st = bootstrap(withEids(transcript));
    expect(users(st)).toHaveLength(5);
    expect(users(st).filter((u) => u.type === "user" && u.steer)).toHaveLength(
      1,
    );
  });

  it("their SSE twins, stamped with the same eids, add nothing", () => {
    let st = bootstrap(withEids(transcript));
    sse.forEach((ev, i) => {
      st = apply(st, { ...ev, eid: i + 1 }, 100 + i);
    });
    expect(users(st)).toHaveLength(5);
    expect(st.items).toHaveLength(5);
  });

  it("an SSE twin with no eid still falls back to the text/time match", () => {
    let st = bootstrap(withEids(transcript));
    for (const ev of sse) st = apply(st, ev, 0);
    expect(users(st)).toHaveLength(5);
  });

  it("a genuinely new user message with a fresh eid is not mistaken for a replay", () => {
    let st = bootstrap(withEids(transcript));
    const again = { ...sse[2], eid: 6 } as WbEvent; // same text, new identity
    st = apply(st, again, 200);
    expect(users(st)).toHaveLength(6);
  });
});

function msg(i: number, eid?: number): WbEvent {
  return {
    kind: "agent_message",
    text: `m${i}`,
    ts: 1000 + i,
    ...(eid ? { eid } : {}),
  };
}

describe("eid window", () => {
  it("accepts out-of-order neighbours inside the window and drops true replays", () => {
    let st = bootstrap(
      withEids([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => msg(i))),
    );
    expect(st.maxEid).toBe(10);
    st = apply(st, msg(12, 12));
    expect(st.items).toHaveLength(11);
    st = apply(st, msg(11, 11)); // arrived late but never seen
    expect(st.items).toHaveLength(12);
    st = apply(st, msg(12, 12)); // replay
    st = apply(st, msg(10, 10)); // replay of a transcript line
    expect(st.items).toHaveLength(12);
    expect(st.maxEid).toBe(12);
  });

  it("anything older than the window is a replay by definition", () => {
    const events = Array.from({ length: 600 }, (_, i) => msg(i + 1, i + 1));
    let st = bootstrap(events);
    expect(st.recentEids.size).toBe(512);
    st = apply(st, msg(5, 5));
    st = apply(st, msg(88, 88));
    expect(st.items).toHaveLength(600);
    st = apply(st, msg(601, 601));
    expect(st.items).toHaveLength(601);
  });

  it("events without eids keep the legacy (kind, ts) window semantics", () => {
    let st = bootstrap([msg(1), msg(2)]);
    st = apply(st, msg(2)); // same kind+ts -> replay
    expect(st.items).toHaveLength(2);
    st = apply(st, msg(3));
    expect(st.items).toHaveLength(3);
  });
});

describe("transcript paging", () => {
  it("bootstrap records the page and the channel numbering", () => {
    const st = bootstrap(withEids([msg(11), msg(12)], 11), {
      page: { total: 12, oldestEid: 11, hasMore: true },
      generation: "abc",
      cursor: 40,
    });
    expect(st.page).toEqual({
      total: 12,
      oldestEid: 11,
      hasMore: true,
      loading: false,
    });
    expect(st.generation).toBe("abc");
    expect(st.cursor).toBe(40);
  });

  it("prepend rebuilds with the older page first and keeps live fields", () => {
    const user = (t: string, eid: number): WbEvent => ({
      kind: "user_message",
      text: t,
      ts: eid,
      eid,
    });
    let st = bootstrap([user("second", 11), msg(12, 12)], {
      page: { total: 12, oldestEid: 11, hasMore: true },
      generation: "g1",
      cursor: 7,
    });
    st = threadReducer(st, { type: "page_loading", loading: true });
    expect(st.page.loading).toBe(true);
    st = threadReducer(st, {
      type: "prepend",
      events: [user("first", 1), msg(2, 2)],
      page: { total: 12, oldestEid: 1, hasMore: false },
    });
    expect(
      st.items.map((it) => (it.type === "user" ? it.text : it.type)),
    ).toEqual(["first", "agent", "second", "agent"]);
    expect(st.page).toEqual({
      total: 12,
      oldestEid: 1,
      hasMore: false,
      loading: false,
    });
    expect(st.rawEvents).toHaveLength(4);
    expect(st.maxEid).toBe(12);
    expect(st.generation).toBe("g1");
    expect(st.cursor).toBe(7);
    // a replay of a prepended line is still recognised
    st = apply(st, user("first", 1));
    expect(st.items).toHaveLength(4);
  });

  it("an empty page only updates the paging state", () => {
    let st = bootstrap([msg(1, 1)], {
      page: { total: 1, oldestEid: 1, hasMore: true },
    });
    st = threadReducer(st, {
      type: "prepend",
      events: [],
      page: { hasMore: false },
    });
    expect(st.items).toHaveLength(1);
    expect(st.page.hasMore).toBe(false);
  });

  it("channel_hello never reaches the item list", () => {
    let st = bootstrap([msg(1, 1)]);
    st = apply(st, {
      kind: "channel_hello",
      generation: "x",
      seq: 3,
      after: 0,
      ts: 1,
    });
    expect(st.items).toHaveLength(1);
  });
});

describe("command output (forensics F-6)", () => {
  const started: WbEvent = {
    kind: "command_started",
    command: "powershell -Command dir",
    status: "in_progress",
    exit_code: null,
    output_tail: null,
    item_id: "item_9",
    ts: 1,
  };
  const streamed = "x".repeat(3000);

  it("keeps the streamed text when the completion tail is shorter, and remembers the size", () => {
    let st = bootstrap([{ kind: "turn_started", ts: 0 }, started]);
    expect(st.turn.active).toBe(true);
    st = threadReducer(st, { type: "stream", commandDelta: streamed });
    st = apply(st, {
      kind: "command_completed",
      command: "powershell -Command dir",
      status: "completed",
      exit_code: 0,
      output_tail: streamed.slice(-1500),
      output_len: 3000,
      output_file: "command_output/item_9.txt",
      item_id: "item_9",
      ts: 2,
    });
    const cmd = st.items.find((it) => it.type === "command");
    if (!cmd || cmd.type !== "command") throw new Error("no command card");
    expect(cmd.output).toHaveLength(3000);
    expect(cmd.done).toBe(true);
    expect(cmd.outputLen).toBe(3000);
    expect(cmd.itemId).toBe("item_9");
    expect(cmd.outputFile).toBe("command_output/item_9.txt");
  });

  it("on reload only the tail exists, and the size says the rest is on the server", () => {
    const st = bootstrap([
      started,
      {
        kind: "command_completed",
        command: "powershell -Command dir",
        status: "completed",
        exit_code: 0,
        output_tail: "tail",
        output_len: 3000,
        item_id: "item_9",
        ts: 2,
      },
    ]);
    const cmd = st.items.find((it) => it.type === "command");
    if (!cmd || cmd.type !== "command") throw new Error("no command card");
    expect(cmd.output).toBe("tail");
    expect(cmd.outputLen).toBe(3000);
  });
});
