/** Slash-command notes (/status, /context, /mcp ...) are client-local cards
 * that never appear in the transcript. Synthetic events; UI lifecycle only. */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import { initialThreadState, threadReducer, type ThreadState } from "./threadReducer";

const T0 = 1700000000;
const note = (title: string, ts: number) => ({ kind: "note", title, lines: ["synthetic line"], ts }) as WbEvent;
const user = (text: string, ts: number, eid: number) => ({ kind: "user_message", text, ts, eid }) as WbEvent;
const shape = (st: ThreadState) => st.items.map((it) => (it.type === "generic" ? `generic:${it.kind}` : it.type));
const notes = (st: ThreadState) => st.items.filter((it) => it.type === "generic" && it.kind === "note");

describe("client-local notes survive transcript rebuilds", () => {
  it("a note issued before the first transcript landed is kept, in time order", () => {
    // user opens the thread and types /status within the first second; the
    // transcript (bootstrap, reset) arrives afterwards
    let st = threadReducer(initialThreadState("synthetic"), { type: "event", ev: note("状态", T0 + 5), seq: 0 });
    expect(notes(st)).toHaveLength(1);
    st = threadReducer(st, {
      type: "bootstrap", reset: true, events: [user("早", T0 + 1, 1), user("晚", T0 + 9, 2)],
      page: {}, generation: "g1", cursor: 2, busy: false,
    });
    expect(shape(st)).toEqual(["user", "generic:note", "user"]);
    const kept = notes(st)[0];
    expect(kept.type === "generic" ? kept.detail : null).toMatchObject({ title: "状态" });
  });

  it("a reconnect that reloads the transcript keeps the note exactly once", () => {
    let st = threadReducer(initialThreadState("synthetic"), {
      type: "bootstrap", reset: true, events: [user("早", T0 + 1, 1)], page: {}, generation: "g1", cursor: 1, busy: false,
    });
    st = threadReducer(st, { type: "event", ev: note("上下文", T0 + 5), seq: 0 });
    // full reload after the channel was rebuilt on the server
    st = threadReducer(st, {
      type: "bootstrap", reset: true, events: [user("早", T0 + 1, 1), user("晚", T0 + 9, 2)], page: {}, generation: "g2", cursor: 2, busy: false,
    });
    expect(shape(st)).toEqual(["user", "generic:note", "user"]);
    // an incremental (non-reset) bootstrap does not duplicate it either
    st = threadReducer(st, { type: "bootstrap", reset: false, events: [user("再", T0 + 12, 3)], page: {}, cursor: 3, busy: false });
    expect(notes(st)).toHaveLength(1);
    expect(shape(st).at(-1)).toBe("user");
  });
});
