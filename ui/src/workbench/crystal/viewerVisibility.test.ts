import { describe, expect, it } from "vitest";
import type { SceneAtom, SceneResponse } from "../../lib/wbTypes";
import { drawnAtomCount } from "./viewerVisibility";

const atom = (extra: Partial<SceneAtom> = {}): SceneAtom => ({ label: "C1", elem: "C", xyz: [1, 1, 1], occ: 1, u_eq: 0.02, sym: false, ...extra });
const scene = { atoms: [atom(), atom({ elem: "H" }), atom({ part: 2 }), atom({ xyz: [8, 1, 1], sym: true, symop: "x+1,y,z" })],
  cell: { a: 10, b: 10, c: 10, alpha: 90, beta: 90, gamma: 90, volume: 1000 } } as SceneResponse;

describe("synthetic display-filter count fixtures", () => {
  it("separates scene instances from visible elements and PARTs", () => {
    expect(drawnAtomCount(scene, [], null, null)).toBe(4);
    expect(drawnAtomCount(scene, ["H"], 1, null)).toBe(2);
    expect(scene.atoms).toHaveLength(4);
  });
  it("uses the same periodic section as the renderer and keeps PART 0", () => {
    expect(drawnAtomCount(scene, ["H"], 1, { axis: 0, center: 0.1, thickness: 0.2 })).toBe(1);
  });
});
