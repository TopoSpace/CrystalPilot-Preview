import { describe, expect, it } from "vitest";
import type { WbEvent } from "../lib/wbTypes";
import { t } from "../lib/i18n";
import { systemText } from "../workbench/chat/GenericRow";
import { initialThreadState, threadReducer, type GenericItem } from "./threadReducer";

// UI fixtures reproduce the native starting/ready/ready shape seen in the
// 2026-09-07 warmup. Counts below are synthetic formatting cases, not inventory.
const startup = (status: string, extra = {}) => ({ kind: "mcp_startup", server: "crystalpilot", status, ts: 1000, ...extra }) as WbEvent;
function replay(events: WbEvent[]) {
  return threadReducer(initialThreadState("synthetic-startup"), { type: "bootstrap", reset: true, events: events.map((ev, i) => ({ ...ev, ts: 1000 + i / 5, eid: i + 1 })) });
}
const readyRows = (events: WbEvent[]) => replay(events).items.filter((it): it is GenericItem => it.type === "generic" && it.kind === "mcp_startup" && (it.detail as { status: string }).status === "ready");

describe("MCP startup presentation", () => {
  it("coalesces repeated native ready without an unknown-count placeholder", () => {
    const rows = readyRows([startup("starting"), startup("ready"), startup("ready")]);
    expect(rows).toHaveLength(1);
    expect(systemText(rows[0])).toBe(t.sysMcpReady);
  });
  it("enriches a native row with a real provided count and retains it on unknown echoes", () => {
    const rows = readyRows([startup("ready"), startup("ready", { n_tools: 3, seconds: 2.1 }), startup("ready")]);
    expect(rows).toHaveLength(1);
    expect(systemText(rows[0])).toBe(`${t.sysMcpReady}（3 ${t.sysMcpToolsUnit} · 2.1 s）`);
  });
  it.each(["starting", "waiting", "timeout", "failed"])("preserves a new %s startup cycle", (status) => {
    expect(readyRows([startup("ready"), startup(status), startup("ready")])).toHaveLength(2);
  });
  it("preserves genuine restart and distinct servers", () => {
    expect(readyRows([startup("ready"), { kind: "engine_restarted", ts: 1001 } as WbEvent, startup("ready"), startup("ready", { server: "another" })])).toHaveLength(3);
  });
  it("never turns waiting or a failed startup into ready", () => {
    const events = [startup("starting"), startup("waiting"), startup("failed", { error: "synthetic failure" })];
    expect(readyRows(events)).toHaveLength(0);
    const last = replay(events).items.at(-1) as GenericItem;
    expect(systemText(last)).toContain("启动失败");
  });
  it.each([null, -1, 1.5, NaN])("does not present invalid count %s", (n_tools) => {
    expect(systemText(readyRows([startup("ready", { n_tools })])[0])).toBe(t.sysMcpReady);
  });
  it("live delivery and transcript rebuild coalesce identically", () => {
    const events = [startup("starting"), startup("ready"), startup("ready")];
    let st = initialThreadState("live");
    events.forEach((ev, i) => { st = threadReducer(st, { type: "event", seq: i + 1, ev }); });
    expect(st.items).toHaveLength(1);
    expect(st.items[0].type === "generic" && systemText(st.items[0])).toBe(t.sysMcpReady);
  });
});
