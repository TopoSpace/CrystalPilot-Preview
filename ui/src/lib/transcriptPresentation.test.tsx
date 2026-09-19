import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { WbEvent } from "./wbTypes";
import { initialThreadState, threadReducer, type ToolCardItem } from "../state/threadReducer";
import { finalReplyIds, pendingTurnIds, retainScientificResult } from "./transcriptPresentation";
import { humanizeTool } from "./toolCards";
import { projectBlocks } from "../workbench/chat/MessageList";
import { AgentMessage, FinalRepliesContext } from "../workbench/chat/AgentMessage";
import { UserBubble } from "../workbench/chat/UserBubble";

const call = (name: string, summary = {}): WbEvent => ({
  kind: "tool_completed", ts: 4, server: "crystalpilot", tool: name, args: {},
  status: "completed", duration_ms: 24500, ok: true, error: null,
  result_tail: JSON.stringify({ ok: true, summary }),
});
const rows: WbEvent[] = [
  { kind: "user_message", ts: 1, text: "Check this model" },
  { kind: "turn_started", ts: 2 },
  { kind: "agent_message", ts: 3, text: "I will inspect it." },
  call("inspect_model", { n_atoms: 45, suspects: [], isolated_atoms: [], space_group: "P 21" }),
  call("inspect_map", { diff_map_max: 0.42, diff_map_min: -0.27 }),
  call("run_checkcif", { counts: { A: 0, B: 0, C: 1, G: 2 } }),
  { kind: "agent_message", ts: 5, text: "Final result." },
  { kind: "turn_completed", ts: 6, status: "completed", duration_ms: 6000 },
];
const stateOf = (events = rows) => threadReducer(initialThreadState("presentation"), { type: "bootstrap", reset: true, events });

describe("scientific transcript hierarchy", () => {
  it("retains successful model, map and validation calls, with chronology and commentary", () => {
    const state = stateOf();
    const visible = projectBlocks(state.items, false).flatMap(b => b.kind === "item" ? [b.item] : []);
    expect(visible.filter(i => i.type === "tool").map(i => i.tool)).toEqual(["inspect_model", "inspect_map", "run_checkcif"]);
    expect(visible.filter(i => i.type === "agent")).toHaveLength(2);
  });
  it("folds routine lookups but does not guess that an unfamiliar scientific tool is unimportant", () => {
    const template = stateOf().items.find(i => i.type === "tool") as ToolCardItem;
    expect(retainScientificResult({ ...template, tool: "read_skill" })).toBe(false);
    expect(retainScientificResult({ ...template, tool: "new_crystal_audit" })).toBe(true);
    expect(retainScientificResult({ ...template, tool: "search", server: "external" })).toBe(false);
  });
  it("only reports observed model findings and measured density", () => {
    const [model, map] = stateOf().items.filter((i): i is ToolCardItem => i.type === "tool");
    expect(humanizeTool(model).chips.map(c => c.text)).toContain("可疑原子 0");
    expect(humanizeTool(map).chips.map(c => c.text).join(" ")).toContain("0.42 e/Å³");
    expect(humanizeTool({ ...model, summary: null }).chips).toEqual([]);
  });
});

describe("message copy actions", () => {
  it("holds completion for all live messages in the turn, while history stays complete", () => {
    const state = stateOf();
    expect(pendingTurnIds(state.items, new Map()).size).toBe(0);
    const items = state.items.map(item => item.type === "agent" ? { ...item, renderId: item.id } : item);
    const agents = items.filter(item => item.type === "agent");
    expect(pendingTurnIds(items, new Map()).size).toBe(1);
    expect(pendingTurnIds(items, new Map([[agents[1].id, false]])).size).toBe(1);
    expect(pendingTurnIds(items, new Map(agents.map(item => [item.id, false]))).size).toBe(0);
  });
  it("gives every user message and only the finished final reply a copy action", () => {
    const state = stateOf();
    const ids = finalReplyIds(state.items);
    expect(ids.size).toBe(1);
    const messages = state.items.filter(i => i.type === "agent");
    expect(renderToStaticMarkup(<FinalRepliesContext.Provider value={ids}><AgentMessage item={messages[0]} /></FinalRepliesContext.Provider>)).not.toContain('data-testid="assistant-copy"');
    expect(renderToStaticMarkup(<FinalRepliesContext.Provider value={ids}><AgentMessage item={messages[1]} /></FinalRepliesContext.Provider>)).toContain('data-testid="assistant-copy"');
    const user = state.items.find(i => i.type === "user")!;
    expect(renderToStaticMarkup(<UserBubble item={user} />)).toContain('data-testid="user-copy"');
  });
  it("does not mislabel completed commentary, a streaming answer or an interrupted turn as a final reply", () => {
    expect(finalReplyIds(stateOf(rows.slice(0, -1)).items).size).toBe(0);
    expect(finalReplyIds(stateOf([...rows.slice(0, -2), rows.at(-1)!]).items).size).toBe(0);
    expect(finalReplyIds(stateOf([...rows.slice(0, -1), { kind: "turn_completed", ts: 6, status: "interrupted", duration_ms: 6000 }]).items).size).toBe(0);
  });
});
