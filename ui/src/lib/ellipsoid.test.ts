import { describe, expect, it } from "vitest";
import {
  ellipsoidMeshes,
  ellipsoidMeshesCached,
  partColor,
} from "./ellipsoid";
import type { SceneAtom } from "./wbTypes";

describe("partColor", () => {
  it("gives distinct colors to the common PART combinations", () => {
    const seen = [1, 2, -1, -2].map(partColor);
    expect(new Set(seen).size).toBe(4);
  });

  it("is stable per part number", () => {
    expect(partColor(1)).toBe(partColor(1));
    expect(partColor(-3)).toBe(partColor(-3));
  });
});

describe("ellipsoidMeshes color overrides", () => {
  const atom = (label: string): SceneAtom => ({
    label,
    elem: "C",
    xyz: [0, 0, 0],
    occ: 0.5,
    u_eq: 0.03,
    sym: false,
    ell: { r: [0.2, 0.2, 0.2], m: [1, 0, 0, 0, 1, 0, 0, 0, 1] },
  });

  it("cached variant is bit-identical and hits on repeat calls", () => {
    const atoms = [atom("C1"), atom("C2")];
    const direct = ellipsoidMeshes(atoms, [0, 1]);
    const cached1 = ellipsoidMeshesCached(atoms, [0, 1]);
    expect(cached1).toEqual(direct); // same math, purely a cache
    const cached2 = ellipsoidMeshesCached(atoms, [0, 1]);
    expect(cached2).toBe(cached1); // identity hit - no re-mesh
    // different tint signature = different entry, not a stale hit
    const tinted = ellipsoidMeshesCached(
      atoms,
      [0, 1],
      new Map([[0, "#123456"]]),
    );
    expect(tinted).not.toBe(cached1);
    expect([...tinted.keys()]).toContain("#123456");
  });

  it("override wins over the element palette and splits the buckets", () => {
    const atoms = [atom("C1"), atom("C2")];
    const plain = ellipsoidMeshes(atoms, [0, 1]);
    expect(plain.size).toBe(1); // both carbon-colored
    const tinted = ellipsoidMeshes(
      atoms,
      [0, 1],
      new Map([[1, "#0ea5e9"]]),
    );
    expect(tinted.size).toBe(2);
    expect([...tinted.keys()]).toContain("#0ea5e9");
  });
});
