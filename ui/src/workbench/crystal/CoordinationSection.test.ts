/** Client-side coordination table (bonding migration 6): metal-ness from
 * the server's `m` flag, ligand counting from the bond kind code. */
import { describe, expect, it } from "vitest";
import type { SceneAtom, SceneBond, SceneResponse } from "../../lib/wbTypes";
import { countGroups, deriveCoordination } from "./CoordinationSection";

function atom(
  label: string,
  elem: string,
  xyz: [number, number, number],
  extra: Partial<SceneAtom> = {},
): SceneAtom {
  return { label, elem, xyz, occ: 1, u_eq: 0.03, sym: false, ...extra };
}

function scene(atoms: SceneAtom[], bonds: SceneBond[]): SceneResponse {
  return { mode: "asu", atoms, bonds } as unknown as SceneResponse;
}

/** ferrocene: Fe + two eta5 rings (ring atoms covalently bonded in cycles) */
function ferrocene(): SceneResponse {
  const atoms: SceneAtom[] = [atom("FE1", "Fe", [0, 0, 0], { m: true })];
  const bonds: SceneBond[] = [];
  const r = 1.2;
  for (let ring = 0; ring < 2; ring += 1) {
    const z = ring === 0 ? 1.65 : -1.65;
    const first = atoms.length;
    for (let k = 0; k < 5; k += 1) {
      const a = (2 * Math.PI * k) / 5;
      atoms.push(atom(`C${ring * 5 + k + 1}`, "C", [r * Math.cos(a), r * Math.sin(a), z]));
      bonds.push([0, first + k, 2]);
    }
    for (let k = 0; k < 5; k += 1) bonds.push([first + k, first + ((k + 1) % 5), 0]);
  }
  return scene(atoms, bonds);
}

describe("deriveCoordination", () => {
  it("counts an eta ring once, as one ligand (ferrocene is CN 2)", () => {
    const rows = deriveCoordination(ferrocene());
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ label: "FE1", cn: 2, etaRings: 2, ligands: "", metalContacts: 0 });
    expect(Number.isFinite(rows[0].minD)).toBe(false);
  });

  it("lists a metal-metal edge as a contact, never a ligand (paddlewheel)", () => {
    const s = scene(
      [
        atom("CU1", "Cu", [0, 0, 0], { m: true }),
        atom("CU2", "Cu", [0, 0, 2.6], { m: true }),
        atom("O1", "O", [1.95, 0, 0]),
        atom("O2", "O", [-1.95, 0, 0]),
        atom("O3", "O", [1.95, 0, 2.6]),
        atom("O4", "O", [-1.95, 0, 2.6]),
      ],
      [[0, 1, 3], [0, 2, 1], [0, 3, 1], [1, 4, 1], [1, 5, 1]],
    );
    const rows = deriveCoordination(s);
    expect(rows.map((r) => [r.label, r.cn, r.ligands, r.metalContacts])).toEqual([
      ["CU1", 2, "O2", 1],
      ["CU2", 2, "O2", 1],
    ]);
    expect(rows[0].minD).toBeCloseTo(1.95, 5);
  });

  it("never decides metal-ness from the element symbol", () => {
    // an exotic / mistyped scattering type without the server flag is not a
    // metal; a plain-looking element WITH the flag is
    const s = scene(
      [atom("XX1", "Xx", [0, 0, 0]), atom("O1", "O", [2, 0, 0]), atom("ZN9", "zn", [5, 0, 0], { m: true }), atom("N1", "N", [7, 0, 0])],
      [[0, 1, 1], [2, 3, 1]],
    );
    expect(deriveCoordination(s).map((r) => r.label)).toEqual(["ZN9"]);
  });

  it("treats a pre-v7 pair-only bond as covalent and keeps working", () => {
    const s = scene(
      [atom("ZN1", "Zn", [0, 0, 0], { m: true }), atom("O1", "O", [2, 0, 0]), atom("O2", "O", [0, 2, 0])],
      [[0, 1], [0, 2]],
    );
    expect(deriveCoordination(s)[0]).toMatchObject({ cn: 2, ligands: "O2" });
  });

  it("skips removed ghosts and symmetry copies of the metal", () => {
    const s = scene(
      [
        atom("ZN1", "Zn", [0, 0, 0], { m: true }),
        atom("O1", "O", [2, 0, 0]),
        atom("O9", "O", [0, 2, 0], { flag: "removed" }),
        atom("ZN1", "Zn", [9, 9, 9], { m: true, sym: true }),
        atom("O1", "O", [11, 9, 9], { sym: true }),
      ],
      [[0, 1, 1], [0, 2, 1], [3, 4, 1]],
    );
    const rows = deriveCoordination(s);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ index: 0, cn: 1 });
    const selected = deriveCoordination(s, 3);
    expect(selected).toHaveLength(2);
    expect(selected.find((row) => row.index === 3)).toMatchObject({ label: "ZN1", cn: 1 });
  });
});

describe("countGroups", () => {
  it("counts connected components among the members only", () => {
    const cov: Set<number>[] = [new Set([1]), new Set([0, 2]), new Set([1]), new Set(), new Set([5]), new Set([4])];
    expect(countGroups([0, 1, 2], cov)).toBe(1);
    expect(countGroups([0, 2], cov)).toBe(2); // 1 is not a member: no bridge
    expect(countGroups([3, 4, 5], cov)).toBe(2);
    expect(countGroups([], cov)).toBe(0);
  });
});
