import { describe, expect, it } from "vitest";
import { humanizeTool } from "./toolCards";
import { safeParseResultTail } from "./resultTail";
import type { ToolCardItem } from "../state/threadReducer";

function tool(summary: object, mode = "check"): ToolCardItem {
  const text = JSON.stringify({ ok: true, summary });
  return { type: "tool", id: "test", ts: 1, server: "crystalpilot", tool: "run_shelxl",
    args: { mode }, status: "ok", rawStatus: "completed", durationMs: 3000, ok: true,
    resultTail: text, error: null, progressLine: null, summary: safeParseResultTail(text), metricsBefore: null, itemId: null, raw: [] };
}

describe("SHELXL presentation from actual run shapes", () => {
  it("does not label missing comparison evidence as disagreement", () => {
    const h = humanizeTool(tool({}));
    expect(String(h.title)).toContain("指标摘要未保留");
    expect(String(h.title)).not.toMatch(/分歧|一致/);
    expect(h.warn).toContain("没有完整");
  });
  it("distinguishes adopted refinement from a cross-engine check", () => {
    const h = humanizeTool(tool({ shelxl: { r1_strong: 0.0766, wr2: 0.2663, goof: 2.18 } }, "adopt"));
    expect(String(h.title)).toContain("SHELXL 精修：R1 0.0766");
    expect(String(h.title)).not.toMatch(/分歧|交叉/);
  });
  it("retains an explicitly measured disagreement", () => {
    const h = humanizeTool(tool({ shelxl: { r1_strong: 0.1 }, delta_r1: 0.02, agrees_with_engine: false }));
    expect(String(h.title)).toContain("分歧");
    expect(String(h.title)).toContain("+0.0200");
  });
  it("shows physical site occupancy with its uncertainty", () => {
    const h = humanizeTool(tool({ shelxl: { r1_strong: 0.05 }, site_occupancies: [
      { atom: "FE04", occupancy: 0.6194, su: 0.0012 },
    ] }, "adopt"));
    expect(h.chips.map((c) => c.text).join(" ")).toContain("FE04 占有率 0.6194 ± 0.0012");
  });
  it("does not turn an unavailable occupancy uncertainty into zero", () => {
    const h = humanizeTool(tool({ shelxl: { r1_strong: 0.05 }, site_occupancies: [
      { atom: "FE04", occupancy: 0.5, su: null },
    ] }));
    expect(h.chips.map((c) => c.text).join(" ")).toContain("s.u. 未定");
  });
  it("names diagnostic deliveries without calling them publication-ready", () => {
    const item = { ...tool({ status: "diagnostic" }), tool: "finalize_delivery" };
    expect(String(humanizeTool(item).title)).toBe("诊断性交付已封存");
    expect(String(humanizeTool({ ...tool({}), tool: "finalize_delivery" }).title)).toContain("状态未报告");
  });
});
