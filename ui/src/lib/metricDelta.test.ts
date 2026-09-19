import { describe, expect, it } from "vitest";
import { metricDelta as delta } from "./metricDelta";

const metricDelta = (cur: number | null | undefined, prev: number | null | undefined,
  digits: number, ideal?: number, stale = false) => delta(cur, prev, digits, ideal, stale, true);

describe("scientific metric deltas", () => {
  it("requires affirmative comparability for arrows and improvement colours", () => {
    expect(delta(0.0381, 0.0656, 4)).toEqual({ changed: true, improved: false,
      worsened: false, direction: null });
    expect(delta(1.1, 1.3, 2, 1, false, false).improved).toBe(false);
  });
  it.each([
    [0.95, 0.80, "up"],
    [1.05, 1.20, "down"],
  ] as const)("GooF %s from %s moves toward 1", (cur, prev, direction) => {
    expect(metricDelta(cur, prev, 2, 1)).toEqual({ changed: true, improved: true,
      worsened: false, direction });
  });

  it("does not reward a falling GooF that moves away from 1", () => {
    expect(metricDelta(0.7, 1, 2, 1)).toEqual({ changed: true, improved: false,
      worsened: true, direction: "down" });
  });

  it("keeps equally distant GooF values neutral, despite floating point noise", () => {
    expect(metricDelta(1.1, 0.9, 2, 1)).toEqual({ changed: true, improved: false,
      worsened: false, direction: "up" });
  });

  it("keeps lower R values distinct from movement toward an ideal", () => {
    expect(metricDelta(0.04, 0.05, 4).improved).toBe(true);
    expect(metricDelta(0.06, 0.05, 4).worsened).toBe(true);
  });

  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])("does not compare missing %s", (cur) => {
    expect(metricDelta(cur, 1, 2).changed).toBe(false);
  });

  it("suppresses stale and sub-precision changes", () => {
    expect(metricDelta(0.04, 0.05, 4, undefined, true).changed).toBe(false);
    expect(metricDelta(0.050001, 0.05, 4).changed).toBe(false);
  });
});
