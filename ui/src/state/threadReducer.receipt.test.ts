/** Steer receipts (round-3 R6): the three states a 插话 bubble can show -
 * pending (optimistic), persisted (the user_message with its eid arrived)
 * and submitted / failed (the steer_receipt that follows it). */
import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import { initialThreadState, threadReducer, type ThreadState, type UserItem } from "./threadReducer";

function run(state: ThreadState, events: WbEvent[]): ThreadState {
  let st = state;
  let seq = st.cursor;
  for (const ev of events) {
    seq += 1;
    st = threadReducer(st, { type: "event", ev, seq });
  }
  return st;
}

function users(st: ThreadState): UserItem[] {
  return st.items.filter((it): it is UserItem => it.type === "user");
}

describe("steer receipts", () => {
  it("optimistic -> persisted (eid) -> submitted", () => {
    let st = threadReducer(initialThreadState("t"), {
      type: "optimistic_user",
      id: "opt1",
      text: "先别删 O5",
      steer: true,
    });
    expect(users(st)[0].pending).toBe(true);
    st = run(st, [
      { kind: "user_message", text: "先别删 O5", steer: true, ts: 10, eid: 41 } as WbEvent,
    ]);
    let u = users(st);
    expect(u).toHaveLength(1);
    expect(u[0].pending).toBe(false);
    expect(u[0].eid).toBe(41);
    expect(u[0].receipt).toBeUndefined();
    st = run(st, [{ kind: "steer_receipt", steer_eid: 41, status: "submitted", ts: 11 } as WbEvent]);
    u = users(st);
    expect(u[0].receipt).toBe("submitted");
    expect(u[0].receiptError).toBeUndefined();
  });

  it("a failed submission keeps the bubble and carries the error", () => {
    const st = run(initialThreadState("t"), [
      { kind: "user_message", text: "改用 P-1 试试", steer: true, ts: 10, eid: 7 } as WbEvent,
      {
        kind: "steer_receipt",
        steer_eid: 7,
        status: "failed",
        error: "RuntimeError: turn already completed",
        ts: 11,
      } as WbEvent,
    ]);
    const u = users(st);
    expect(u).toHaveLength(1);
    expect(u[0].text).toBe("改用 P-1 试试");
    expect(u[0].receipt).toBe("failed");
    expect(u[0].receiptError).toContain("turn already completed");
  });

  it("matches by eid, not by recency", () => {
    const st = run(initialThreadState("t"), [
      { kind: "user_message", text: "一", steer: true, ts: 1, eid: 1 } as WbEvent,
      { kind: "user_message", text: "二", steer: true, ts: 2, eid: 2 } as WbEvent,
      { kind: "steer_receipt", steer_eid: 1, status: "failed", error: "x", ts: 3 } as WbEvent,
    ]);
    const u = users(st);
    expect(u[0].receipt).toBe("failed");
    expect(u[1].receipt).toBeUndefined();
  });

  it("without an eid falls back to the latest steer still unconfirmed", () => {
    const st = run(initialThreadState("t"), [
      { kind: "user_message", text: "一", steer: true, ts: 1 } as WbEvent,
      { kind: "user_message", text: "普通消息", steer: false, ts: 2 } as WbEvent,
      { kind: "steer_receipt", status: "submitted", ts: 3 } as WbEvent,
    ]);
    const u = users(st);
    expect(u[0].receipt).toBe("submitted");
    expect(u[1].receipt).toBeUndefined();
  });

  it("a replayed transcript (user_steer + receipt) gives the same state", () => {
    const st = run(initialThreadState("t"), [
      { kind: "user_steer", text: "看一下堆积", ts: 1, eid: 9 } as WbEvent,
      { kind: "steer_receipt", steer_eid: 9, status: "submitted", ts: 2, eid: 10 } as WbEvent,
    ]);
    const u = users(st);
    expect(u).toHaveLength(1);
    expect(u[0].steer).toBe(true);
    expect(u[0].receipt).toBe("submitted");
    // the receipt is not a row of its own
    expect(st.items.filter((it) => it.type !== "user")).toHaveLength(0);
  });
});
