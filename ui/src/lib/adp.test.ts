import { describe, expect, it } from "vitest";
import { adpAnomalies, adpReasons } from "./adp";
import type { SceneAtom } from "./wbTypes";

function atom(over: Partial<SceneAtom> = {}): SceneAtom {
  return {
    label: "C1",
    elem: "C",
    xyz: [0, 0, 0],
    occ: 1,
    u_eq: 0.03,
    sym: false,
    ...over,
  };
}

describe("adpReasons", () => {
  it("does not diagnose a missing ADP as a measured zero", () => {
    expect(adpReasons(atom({ adp_known: false, u_eq: null, ell: { npd: true } }))).toEqual([]);
  });

  it("healthy atom has no reasons", () => {
    expect(adpReasons(atom())).toEqual([]);
    expect(
      adpReasons(atom({ ell: { r: [0.3, 0.25, 0.2], m: [], npd: false } })),
    ).toEqual([]);
  });

  it("flags NPD, extreme axis ratio and U_eq extremes", () => {
    expect(adpReasons(atom({ ell: { npd: true } }))).toHaveLength(1);
    const cigar = adpReasons(
      atom({ ell: { r: [0.9, 0.3, 0.15], m: [] } }),
    );
    expect(cigar.some((s) => s.includes("轴比"))).toBe(true);
    expect(adpReasons(atom({ u_eq: 0.25 })).some((s) => s.includes("过大"))).toBe(
      true,
    );
    expect(
      adpReasons(atom({ u_eq: 0.001 })).some((s) => s.includes("过小")),
    ).toBe(true);
  });

  it("ignores H and removed ghosts", () => {
    expect(adpReasons(atom({ elem: "H", u_eq: 0.5 }))).toEqual([]);
    expect(adpReasons(atom({ flag: "removed", u_eq: 0.5 }))).toEqual([]);
  });
});

describe("adpAnomalies", () => {
  it("skips symmetry copies and keeps originals", () => {
    const atoms = [
      atom({ u_eq: 0.3 }),
      atom({ label: "C1'", u_eq: 0.3, sym: true }),
      atom({ label: "C2" }),
    ];
    const out = adpAnomalies(atoms);
    expect(out).toHaveLength(1);
    expect(out[0].index).toBe(0);
    expect(out[0].reasons.length).toBeGreaterThan(0);
  });
});
