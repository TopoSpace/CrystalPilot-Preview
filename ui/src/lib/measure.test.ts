import { describe, expect, it } from "vitest";
import { angle, distance, measureReadout, torsion } from "./measure";

describe("measure math", () => {
  it("distance", () => {
    expect(distance([0, 0, 0], [3, 4, 0])).toBeCloseTo(5, 10);
  });

  it("right angle", () => {
    expect(angle([1, 0, 0], [0, 0, 0], [0, 1, 0])).toBeCloseTo(90, 8);
  });

  it("linear angle", () => {
    expect(angle([-1, 0, 0], [0, 0, 0], [2, 0, 0])).toBeCloseTo(180, 8);
  });

  it("torsion sign convention (staggered = ±60)", () => {
    // butane-like: 60° gauche
    const t = torsion(
      [1, 0, 0],
      [0, 0, 0],
      [0, 0, 1.5],
      [Math.cos(Math.PI / 3), Math.sin(Math.PI / 3), 1.5],
    );
    expect(Math.abs(t)).toBeCloseTo(60, 6);
  });

  it("cis torsion is 0", () => {
    expect(
      torsion([1, 0, 0], [0, 0, 0], [0, 0, 1.5], [1, 0, 1.5]),
    ).toBeCloseTo(0, 6);
  });

  it("readout formats", () => {
    expect(
      measureReadout(["W1", "C3"], [[0, 0, 0], [2.031, 0, 0]])?.text,
    ).toBe("W1–C3  2.031 Å");
    expect(
      measureReadout(
        ["C1", "W1", "C2"],
        [[1, 0, 0], [0, 0, 0], [0, 1, 0]],
      )?.text,
    ).toContain("90.00°");
    expect(measureReadout(["A"], [[0, 0, 0]])).toBeNull();
  });
});
