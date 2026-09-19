/** Cartesian↔fractional round-trip on a low-symmetry cell (P2-4 slab). */
import { describe, expect, it } from "vitest";
import { cellVectors, fracCoord, fracRows } from "./cellMath";
import type { SceneCell } from "./wbTypes";

const TRICLINIC: SceneCell = {
  a: 7.1,
  b: 9.3,
  c: 11.7,
  alpha: 82.4,
  beta: 101.2,
  gamma: 96.8,
  volume: 0,
};

describe("fracRows / fracCoord", () => {
  it("inverts the orthogonalization matrix (frac→cart→frac round-trip)", () => {
    const [va, vb, vc] = cellVectors(TRICLINIC);
    const rows = fracRows(TRICLINIC);
    const fracs: [number, number, number][] = [
      [0, 0, 0],
      [0.25, 0.5, 0.75],
      [1.3, -0.2, 0.98],
    ];
    for (const f of fracs) {
      const cart: [number, number, number] = [
        f[0] * va[0] + f[1] * vb[0] + f[2] * vc[0],
        f[0] * va[1] + f[1] * vb[1] + f[2] * vc[1],
        f[0] * va[2] + f[1] * vb[2] + f[2] * vc[2],
      ];
      for (const axis of [0, 1, 2] as const) {
        expect(fracCoord(rows, axis, cart)).toBeCloseTo(f[axis], 8);
      }
    }
  });
});
