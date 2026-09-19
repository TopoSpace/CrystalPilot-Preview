import { describe, expect, it } from "vitest";
import { humanizeTool, parseViewImages } from "./toolCards";
import type { ToolCardItem } from "../state/threadReducer";

/** render_views writes `{stem}_{state}_{view}.png` (structviews.py:227). */
const VIEW = "H:/p/.crystalpilot/views/v101530_asu_a.png";
const SUPER = "H:/p/.crystalpilot/views/sit_supercell_c.png";

function item(tool: string, summary: unknown): ToolCardItem {
  return {
    id: "t1",
    tool,
    args: {},
    status: "done",
    summary: { parsed: { ok: true, summary } },
    durationMs: 1200,
  } as unknown as ToolCardItem;
}

describe("parseViewImages", () => {
  it("reads the view_structure shape ({view, path})", () => {
    const got = parseViewImages([{ view: "a", path: VIEW }]);
    expect(got).toEqual([{ path: VIEW, label: "不对称单元 · 沿 a 轴" }]);
  });

  it("reads the situation_report shape (bare paths)", () => {
    const got = parseViewImages([SUPER]);
    expect(got).toHaveLength(1);
    expect(got[0].path).toBe(SUPER);
    expect(got[0].label).toContain("2×2×2");
  });

  it("skips malformed entries instead of rendering broken images", () => {
    expect(parseViewImages([null, 42, {}, { view: "a" }])).toEqual([]);
    expect(parseViewImages(undefined)).toEqual([]);
  });
});

describe("vision tool cards", () => {
  it("view_structure shows the pictures, not a JSON blob", () => {
    const h = humanizeTool(
      item("view_structure", {
        state: "supercell",
        views: ["a", "c"],
        n_atoms_drawn: 63,
        images: [{ view: "a", path: VIEW }, { view: "c", path: SUPER }],
      }),
    );
    expect(h.title).toContain("2×2×2");
    expect(h.body).not.toBeNull();
    expect(h.chips.map((c) => c.text)).toContain("63 原子");
  });

  it("situation_report surfaces conflicts as the headline", () => {
    const h = humanizeTool(
      item("situation_report", {
        conflicts: ["数据是 HKLF5 批次而会话无 BASF/twin 标志"],
        narrative: ["精修轨迹：最近 5 个节点 R1 已收敛"],
        images: [SUPER],
      }),
    );
    expect(h.title).toContain("冲突");
    expect(h.tone).toBe("warn");
    expect(h.warn).toContain("HKLF5");
    expect(h.body).not.toBeNull();
  });

  it("situation_report without renders still humanizes", () => {
    const h = humanizeTool(item("situation_report", { narrative: [] }));
    expect(h.title).toBe("全局现状综述");
    expect(h.tone).toBeNull();
  });
});

describe("data-quality plots", () => {
  const shells = Array.from({ length: 12 }, (_, i) => ({
    d_max: 10 - i * 0.7,
    d_min: 9.3 - i * 0.7,
    cc_one_half: 0.99 - i * 0.06,
    i_over_sigma: 40 - i * 3,
    completeness: 0.99 - i * 0.02,
    r_meas: 0.03 + i * 0.02,
  }));

  it("estimate_resolution renders the shell curves, not a JSON wall", () => {
    const h = humanizeTool(
      item("estimate_resolution", {
        mode: "hkl_shells",
        suggested_d_min: 0.82,
        current_d_min: 0.58,
        merge_laue_class: "mmm",
        centring_inferred: "P",
        shells,
      }),
    );
    expect(h.title).toContain("0.82");
    expect(h.body).not.toBeNull();
    // an observe-style gray row would collapse the plot away
    expect(h.observe).toBe(false);
    expect(h.chips.map((c) => c.text)).toContain("12 壳层");
  });

  it("too few shells to plot degrades to numbers only", () => {
    const h = humanizeTool(
      item("estimate_resolution", {
        suggested_d_min: 0.9,
        shells: shells.slice(0, 2),
      }),
    );
    expect(h.body).toBeNull();
  });

  it("the DIALS route (no shell table) still humanizes", () => {
    const h = humanizeTool(
      item("estimate_resolution", {
        suggested_d_min: 0.75,
        by_metric: { cc_half: 0.75 },
        source: "scaled.refl",
      }),
    );
    expect(h.title).toContain("0.75");
    expect(h.body).toBeNull();
  });
});
