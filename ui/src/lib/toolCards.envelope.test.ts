/** Round-3 WP1: the status envelope reaches the row. A tool that ran and
 * changed nothing says 无变化 first; a verdict of inconclusive says 未定论;
 * a budgeted loop that stopped early says 超时. */
import { describe, expect, it } from "vitest";
import type { ToolCardItem } from "../state/threadReducer";
import { safeParseResultTail, NON_METRIC_CONTAINERS } from "./resultTail";
import { envelopeChips, humanizeTool } from "./toolCards";

function item(tool: string, summary: Record<string, unknown>): ToolCardItem {
  return {
    type: "tool",
    id: `t-${tool}`,
    ts: 0,
    server: "crystalpilot",
    tool,
    args: {},
    status: "ok",
    rawStatus: "completed",
    durationMs: 120,
    ok: true,
    resultTail: null,
    error: null,
    progressLine: null,
    summary: { parsed: { ok: true, summary, artifacts: {}, error: null } },
    metricsBefore: null,
    itemId: null,
    raw: [],
  };
}

const env = (over: Record<string, unknown>) => ({
  execution: "ran",
  scientific_outcome: null,
  state_changed: null,
  no_change: { value: false, reason: null },
  applicability: [],
  artifact_index: {},
  ...over,
});

describe("status envelope on the tool row", () => {
  it("says 无变化 first when the tool ran and changed nothing", () => {
    const h = humanizeTool(
      item("fit_fragment", {
        added: [],
        refused: [{ template_index: 0 }],
        no_state_change: true,
        tool_status: env({ no_change: { value: true, reason: "all refused" },
                           scientific_outcome: { verdict: "inconclusive", reasons: [], measured_by: "x" } }),
      }),
    );
    expect(h.chips[0]).toEqual({ text: "无变化", tone: "warn" });
    expect(h.chips.map((c) => c.text)).toContain("未定论");
  });

  it("says 超时 for a partial result and nothing for a plain ran", () => {
    expect(envelopeChips({ tool_status: env({ execution: "timeout" }) }).map((c) => c.text)).toEqual([
      "超时 · 部分结果",
    ]);
    expect(envelopeChips({ tool_status: env({}) })).toEqual([]);
    expect(envelopeChips({})).toEqual([]);
    expect(envelopeChips({ tool_status: env({ scientific_outcome: { verdict: "against" } }) })[0]).toEqual({
      text: "证据相反",
      tone: "danger",
    });
  });

  it("is skipped by the metric tail parser", () => {
    expect(NON_METRIC_CONTAINERS.has("tool_status")).toBe(true);
    const parsed = safeParseResultTail(
      JSON.stringify({
        ok: true,
        summary: {
          node: "n0002",
          r1_strong: 0.0412,
          tool_status: env({ state_changed: { changed: true, node_before: "n0001", node_after: "n0002" } }),
        },
      }),
    );
    expect(parsed?.node).toBe("n0002");
    expect(parsed?.r1).toBeCloseTo(0.0412, 6);
  });
});
