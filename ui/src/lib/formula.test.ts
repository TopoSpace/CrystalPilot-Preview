import { describe, expect, it } from "vitest";
import { formulaCount, hillFormula } from "./formula";

describe("hillFormula", () => {
  it("sums occupancies so a two-position disorder is not counted twice", () => {
    const atoms = [
      { elem: "C", occ: 1 },
      { elem: "C", occ: 0.7077 },
      { elem: "C", occ: 0.2923 },
      { elem: "H", occ: 0.7077 },
      { elem: "H", occ: 0.2923 },
      { elem: "N", occ: 1 },
      { elem: "O", occ: 1 },
    ];
    expect(hillFormula(atoms)).toEqual([
      { elem: "C", count: 2 },
      { elem: "H", count: 1 },
      { elem: "N", count: 1 },
      { elem: "O", count: 1 },
    ]);
  });
  it("skips symmetry copies, keeps Hill order, shows a half-occupied site as 0.5", () => {
    const atoms = [
      { elem: "O", occ: 0.5 },
      { elem: "Zn", occ: 1 },
      { elem: "C", occ: 1 },
      { elem: "C", occ: 1, sym: true },
      { elem: "Cl" },
    ];
    const f = hillFormula(atoms)!;
    expect(f.map((t) => t.elem)).toEqual(["C", "Cl", "O", "Zn"]);
    expect(f.find((t) => t.elem === "O")!.count).toBe(0.5);
    expect(f.find((t) => t.elem === "C")!.count).toBe(1);
    expect(formulaCount(0.5)).toBe("0.5");
    expect(formulaCount(16)).toBe("16");
    expect(hillFormula([])).toBeNull();
  });
});
