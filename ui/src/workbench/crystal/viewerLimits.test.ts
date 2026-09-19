import { describe, expect, it, vi } from "vitest";
import {
  MAX_Q_PEAK_SPHERES,
  applyViewerDepth,
  atomDepthSpan,
  overlayCoverage,
  qPeakDrawPlan,
} from "./viewerLimits";

describe("viewer camera depth", () => {
  it("uses public fog/slab APIs with a symmetric full-atom default", () => {
    const viewer = { enableFog: vi.fn(), setSlab: vi.fn() };
    const span = atomDepthSpan([
      { xyz: [0, 0, 0] },
      { xyz: [3, 4, 12] },
    ]);

    applyViewerDepth(viewer, { fog: false, fogStart: 0.55, clip: 1 }, span);

    expect(span).toBe(13);
    expect(viewer.enableFog).toHaveBeenCalledWith(false);
    expect(viewer.setSlab).toHaveBeenCalledWith(-13, 13);
  });

  it("includes a displaced scene around the preserved camera centre", () => {
    const atoms = [{ xyz: [100, 0, 0] }, { xyz: [102, 1, 0] }];
    expect(atomDepthSpan(atoms)).toBe(5);
    expect(atomDepthSpan(atoms, [0, 0, 0])).toBeGreaterThan(102);
    expect(atomDepthSpan(atoms, [-101, 0, 0])).toBeLessThan(7);
    expect(atomDepthSpan(atoms, [NaN, 0, 0])).toBe(5);
  });

  it("bounds fog and clip values before calling 3Dmol", () => {
    const viewer = { enableFog: vi.fn(), setSlab: vi.fn() };
    applyViewerDepth(viewer, { fog: true, fogStart: 8, clip: -1 }, 20);

    expect(viewer.enableFog).toHaveBeenCalledWith({ fogStart: 0.9, fogEnd: 1 });
    expect(viewer.setSlab).toHaveBeenCalledWith(-2, 2);
  });
});

describe("independent overlay budgets", () => {
  it("caps symmetry at 8 tiles and Q peaks at 3000 spheres", () => {
    const coverage = overlayCoverage(64, 64, 100);
    expect(coverage.symmetry).toEqual({ drawnTiles: 8, requestedTiles: 64 });
    expect(coverage.peaks).toEqual({ drawnSpheres: 3000, requestedSpheres: 6400 });
    expect(qPeakDrawPlan(100, 64)).toEqual({
      peaksPerTile: 100,
      tileCount: 30,
      sphereCount: 3000,
    });
  });

  it("reports uncapped small layers at their actual counts", () => {
    expect(overlayCoverage(4, 4, 20)).toEqual({
      symmetry: { drawnTiles: 4, requestedTiles: 4 },
      peaks: { drawnSpheres: 80, requestedSpheres: 80 },
    });
  });

  it("never exceeds the Q budget when one cell alone has too many peaks", () => {
    const plan = qPeakDrawPlan(4500, 3);
    expect(plan).toEqual({
      peaksPerTile: MAX_Q_PEAK_SPHERES,
      tileCount: 1,
      sphereCount: MAX_Q_PEAK_SPHERES,
    });
    expect(overlayCoverage(3, 3, 4500).peaks).toEqual({
      drawnSpheres: 3000,
      requestedSpheres: 13500,
    });
  });

  it("keeps independent counts honest after the 64-tile range cap", () => {
    const coverage = overlayCoverage(216, 64, 1);
    expect(coverage.symmetry).toEqual({ drawnTiles: 8, requestedTiles: 216 });
    expect(coverage.peaks).toEqual({ drawnSpheres: 64, requestedSpheres: 216 });
  });
});
