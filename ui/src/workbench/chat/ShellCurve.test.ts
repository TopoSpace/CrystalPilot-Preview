import { describe, expect, it } from "vitest";
import { shellPlot } from "./ShellCurve";

/** A typical falling-off dataset: 12 shells, high resolution last. */
const shells = Array.from({ length: 12 }, (_, i) => ({
  d_max: 10 - i * 0.75,
  d_min: 9.25 - i * 0.75,
  cc_one_half: 0.99 - i * 0.07,
  i_over_sigma: 40 - i * 3.2,
  completeness: 0.99 - i * 0.01,
}));

function xs(pts: string): number[] {
  return pts.split(" ").map((p) => Number(p.split(",")[0]));
}
function ys(pts: string): number[] {
  return pts.split(" ").map((p) => Number(p.split(",")[1]));
}

describe("shellPlot geometry", () => {
  it("puts low resolution on the left and high on the right", () => {
    const plot = shellPlot(shells)!;
    const x = xs(plot.lines[0].pts);
    // shells arrive coarse -> fine, and x = 1/d^2 must increase with them
    expect(x[0]).toBeLessThan(x[x.length - 1]);
    expect([...x]).toEqual([...x].sort((a, b) => a - b));
    expect(plot.dLo).toBeGreaterThan(plot.dHi); // 9.25 A ... 1.0 A
  });

  it("inverts y so a falling CC1/2 draws downwards", () => {
    const plot = shellPlot(shells)!;
    const cc = plot.lines.find((l) => l.key === "cc_one_half")!;
    const y = ys(cc.pts);
    // CC1/2 decreases across the shells; in SVG that means y increases
    expect(y[0]).toBeLessThan(y[y.length - 1]);
    // 1.0 sits at the top of the box, 0.0 at the bottom
    expect(plot.py(1)).toBeLessThan(plot.py(0));
  });

  it("scales I/sigma onto the shared axis by its own maximum", () => {
    const plot = shellPlot(shells)!;
    expect(plot.isoMax).toBeCloseTo(40, 5);
    const iso = plot.lines.find((l) => l.key === "i_over_sigma")!;
    // the first point is the maximum -> normalized 1.0 -> top of the box
    expect(ys(iso.pts)[0]).toBeCloseTo(plot.py(1), 5);
  });

  it("accepts completeness as a percentage as well as a fraction", () => {
    const pct = shells.map((s) => ({
      ...s,
      completeness: (s.completeness as number) * 100,
    }));
    const a = shellPlot(shells)!.lines.find((l) => l.key === "completeness")!;
    const b = shellPlot(pct)!.lines.find((l) => l.key === "completeness")!;
    expect(b.pts).toBe(a.pts);
  });

  it("drops series the shells do not carry", () => {
    const bare = shells.map((s) => ({ d_min: s.d_min, d_max: s.d_max }));
    expect(shellPlot(bare)).toBeNull();
  });

  it("needs at least three shells to draw anything", () => {
    expect(shellPlot(shells.slice(0, 2))).toBeNull();
    expect(shellPlot([])).toBeNull();
  });

  it("survives a degraded table with missing entries", () => {
    const holey = shells.map((s, i) =>
      i % 3 === 0 ? { d_min: s.d_min, d_max: s.d_max } : s,
    );
    const plot = shellPlot(holey)!;
    const cc = plot.lines.find((l) => l.key === "cc_one_half")!;
    expect(cc.pts.split(" ").length).toBe(8); // 12 - 4 dropped
  });
});
