/** Stage track: the last stage-bearing tool sets the stage, a
 * situation_report reading overrides it, and turns file under the stage of
 * their most-used tool. */
import { describe, expect, it } from "vitest";
import type { ChatItem, ToolCardItem, TurnStatusItem } from "../state/threadReducer";
import { STAGES, stageState, stageTrack } from "./stages";

let n = 0;
function tool(name: string, status: ToolCardItem["status"] = "ok", parsed?: unknown): ToolCardItem {
  n += 1;
  return {
    type: "tool",
    id: `t${n}`,
    ts: n,
    server: "crystalpilot",
    tool: name,
    args: {},
    status,
    rawStatus: status,
    durationMs: 1,
    ok: status === "ok",
    resultTail: null,
    error: null,
    progressLine: null,
    summary: parsed === undefined ? null : { parsed },
    metricsBefore: null,
    itemId: null,
    raw: [],
  };
}
function turn(tools: [string, number][]): TurnStatusItem {
  n += 1;
  return {
    type: "turn",
    id: `u${n}`,
    ts: n,
    phase: "completed",
    status: "completed",
    durationMs: 10,
    error: null,
    summary: { tools, nodes: [], nCommands: 0, r1From: null, r1To: null },
  };
}

describe("stageTrack", () => {
  it("empty transcript has no stage", () => {
    const t = stageTrack([]);
    expect(t.current).toBeNull();
    expect(t.stages.map((s) => s.id)).toEqual([...STAGES]);
  });

  it("the last successful stage-bearing tool wins; failures and observe tools do not count", () => {
    const items: ChatItem[] = [
      tool("run_shelxt"),
      tool("edit_atoms"),
      tool("refine"),
      tool("refine", "error"),
      tool("list_nodes"),
    ];
    const t = stageTrack(items);
    expect(t.current).toBe("refine");
    expect(t.basis).toBe("tool");
    expect(t.stages.find((s) => s.id === "refine")!.nTools).toBe(1);
    expect(t.stages.find((s) => s.id === "refine")!.observed).toBe(true);
    expect(t.stages.find((s) => s.id === "solve")!.nTools).toBe(1);
    expect(t.stages.find((s) => s.id === "data")!.observed).toBe(false);
  });

  it("situation_report's stage reading overrides the tool reading", () => {
    const items: ChatItem[] = [
      tool("refine"),
      tool("situation_report", "ok", { stage: { stage: "建模", basis: "x" } }),
    ];
    const t = stageTrack(items);
    expect(t.current).toBe("model");
    expect(t.basis).toBe("situation_report");
    // an unknown stage string is ignored, not mis-mapped
    expect(stageTrack([tool("refine"), tool("situation_report", "ok", { stage: "?" })]).current).toBe("refine");
  });

  it("only get_geometry observes validation and no implied predecessors", () => {
    const t = stageTrack([tool("get_geometry")]);
    expect(t.current).toBe("validate");
    expect(t.stages.find((s) => s.id === "validate")!.observed).toBe(true);
    expect(t.stages.filter((s) => s.id !== "validate").every((s) => !s.observed)).toBe(true);
  });

  it("direct CIF import observes model without claiming data, symmetry or solve", () => {
    const t = stageTrack([tool("import_cif_model")]);
    expect(t.current).toBe("model");
    expect(t.stages.find((s) => s.id === "model")!.observed).toBe(true);
    expect(t.stages.slice(0, 3).every((s) => !s.observed)).toBe(true);
  });

  it("a failed stage tool is observed but cannot declare the current stage", () => {
    const t = stageTrack([tool("run_shelxt", "error")]);
    const solve = t.stages.find((s) => s.id === "solve")!;
    expect(t.current).toBeNull();
    expect(solve.observed).toBe(true);
    expect(solve.nTools).toBe(0);
  });

  it("turns file under the stage of their most-used tool, later stage on ties", () => {
    const items: ChatItem[] = [
      tool("refine"),
      turn([["refine", 3], ["edit_atoms", 1]]),
      turn([["write_outputs", 1], ["run_checkcif", 1]]),
    ];
    const t = stageTrack(items);
    expect(t.stages.find((s) => s.id === "refine")!.turns).toHaveLength(1);
    expect(t.stages.find((s) => s.id === "deliver")!.turns).toHaveLength(1);
    expect(t.stages.find((s) => s.id === "validate")!.turns).toHaveLength(0);
  });

  it("stageState uses observation rather than pipeline position", () => {
    expect(stageState("data", "refine", true)).toBe("visited");
    expect(stageState("symmetry", "refine", false)).toBe("pending");
    expect(stageState("refine", "refine", false)).toBe("current");
    expect(stageState("deliver", "refine", false)).toBe("pending");
    expect(stageState("data", null, true)).toBe("visited");
    expect(stageState("data", null, false)).toBe("pending");
  });
});
