import { describe, expect, it } from "vitest";
import {
  criteriaSummary,
  interactionGeometry,
  interactionLabel,
  interactionQuote,
} from "./interactions";
import type { InteractionRow } from "./wbTypes";
import { zh } from "./zh";

const base = {
  dist: 2.8, boundary: false, sym: "x,y,z", sym_i: "x,y,z", op: "x,y,z",
  p: [0, 0, 0] as [number, number, number], q: [2.8, 0, 0] as [number, number, number],
  ai: 0, bi: 2,
};

const hbond: InteractionRow = {
  ...base, kind: "hbond", passes: true, d: "O1", h: "H1", a: "O2",
  d_DA: 2.8, d_HA: 1.84, angle: 180, status: null,
};

const CRIT = {
  hbond: { set: "olex2", d_DA_max_A: 2.9, angle_DHA_min_deg: 150, source: "Olex2 htab" },
  pipi: { set: "olex2", d_cc_max_A: 4.0, alpha_max_deg: 30, slip_max_A: 3.0 },
};

describe("interaction text", () => {
  it("names atoms by label and the image by its operator, never an ordinal", () => {
    const q = interactionQuote(
      { ...hbond, sym: "-x+1,y+1/2,-z+1/2", boundary: true },
      { h_source: "riding", criteria: CRIT },
    );
    expect(q).toContain("氢键 O1–H1···O2（对称码 -x+1,y+1/2,-z+1/2）");
    expect(q).toContain("D···A 2.80 Å、H···A 1.84 Å、∠D–H···A 180.0°");
    expect(q).toContain("满足 olex2: d_DA_max 2.9 Å、angle_DHA_min 150° 判据");
    expect(q).toContain("骑乘 H");
    expect(q).toContain("伙伴在显示范围外");
    expect(q).not.toMatch(/#\d|序号/);
  });

  it("omits the operator for a same-molecule pair and the H note for refined H", () => {
    const q = interactionQuote(hbond, { h_source: "refined", criteria: CRIT });
    expect(q).not.toContain("对称码");
    expect(q).not.toContain("骑乘");
    expect(q).toContain("HTAB");
  });

  it("degrades to D···A only when the model has no H", () => {
    const row: InteractionRow = { ...hbond, h: null, d_HA: null, angle: null, status: "no_H_D···A_only" };
    expect(interactionGeometry(row)).toEqual([["D···A", "2.80 Å"], ["H", "无 H：只报 D···A，角度不可得"]]);
    expect(interactionLabel(row)).toBe("O1–?···O2");
  });

  it("reports both perpendicular distances and both slips of a pi stack", () => {
    const row: InteractionRow = {
      ...base, kind: "pipi", passes: false, ring_a: "C1..C6", ring_b: "C7..C12",
      d_cc: 3.808, alpha: 25, d_perp_ab: 3.5, d_perp_ba: 3.172, slip_ab: 1.5, slip_ba: 2.107,
    };
    const g = interactionGeometry(row);
    expect(g).toEqual([
      ["质心距", "3.81 Å"], ["法线夹角 α", "25.0°"],
      ["垂直距离 a→b / b→a", "3.50 / 3.17 Å"], ["滑移 a→b / b→a", "1.50 / 2.11 Å"],
    ]);
    const q = interactionQuote(row, { h_source: "absent", criteria: CRIT });
    expect(q).toContain("π–π 堆积 环 C1..C6 ⋯ 环 C7..C12");
    expect(q).toContain("不满足 olex2");
    expect(q).not.toContain("骑乘");
  });

  it("summarises criteria from the echoed block", () => {
    expect(criteriaSummary(CRIT.pipi)).toBe("olex2: d_cc_max 4 Å、alpha_max 30°、slip_max 3 Å");
    expect(criteriaSummary(undefined)).toBe("");
  });
});

describe("interactionQuote on a canonical row", () => {
  it("names the operator from `op` when the row has no display `sym`", () => {
    const row = {
      kind: "hbond" as const,
      dist: 2.8,
      passes: true,
      op: "x-1,y,z",
      d: "O1",
      h: "H1",
      a: "O2",
      d_DA: 2.8,
      d_HA: 1.84,
      angle: 180,
    };
    const q = interactionQuote(row, {
      h_source: "refined",
      criteria: { hbond: { set: "olex2", d_DA_max_A: 2.9, angle_DHA_min_deg: 150 } },
    });
    expect(q).toContain("O1–H1···O2");
    expect(q).toContain("x-1,y,z");
    expect(q).toContain("满足");
    expect(q).not.toContain(zh.ixBoundary);
    expect(interactionLabel(row)).toBe("O1–H1···O2");
  });
});

describe("interactionLabel for C–H···X", () => {
  it("reads the carrier under `d` (engine key) as well as `c`", () => {
    const row = { kind: "chx" as const, dist: 2.24, passes: true, op: "x,y,z",
      d: "C13", h: "H13A", a: "O4", d_DA: 3.1, d_HA: 2.24, angle: 122.7 };
    expect(interactionLabel(row)).toBe("C13–H13A···O4");
    expect(interactionLabel({ ...row, d: undefined, c: "C13" })).toBe("C13–H13A···O4");
  });
});

describe("criteriaSummary", () => {
  it("lists thresholds (unit-suffixed keys) and skips diagnostic counts", () => {
    const s = criteriaSummary({
      set: "olex2",
      source: "Olex2 htab defaults",
      d_DA_max_A: 2.9,
      angle_DHA_min_deg: 150,
      polar_atoms_without_bonded_H: 6,
      vdw_fallback_used: 0,
    });
    expect(s).toBe("olex2: d_DA_max 2.9 Å、angle_DHA_min 150°");
  });
});
