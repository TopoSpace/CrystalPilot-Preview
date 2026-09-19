import { describe, expect, it } from "vitest";
import {
  polyhedraMeshes,
  polyhedraMeshesCached,
  visiblePolyhedra,
} from "./polyhedra";
import { elementColor } from "../../lib/ellipsoid";
import type { SceneAtom, ScenePolyhedron } from "../../lib/wbTypes";

function metal(elem: string, xyz: [number, number, number]): SceneAtom {
  return {
    label: `${elem}1`,
    elem,
    xyz,
    occ: 1,
    u_eq: 0.02,
    sym: false,
  };
}

/** Regular tetrahedron centred on the origin; the last face is wound the
 * opposite way from the first three so both orientation branches run. */
function tetra(metalIdx: number): ScenePolyhedron {
  return {
    metal: metalIdx,
    vertices: [
      [1, 1, 1],
      [1, -1, -1],
      [-1, 1, -1],
      [-1, -1, 1],
    ],
    faces: [
      [0, 1, 2],
      [0, 2, 3],
      [0, 3, 1],
      [1, 2, 3],
    ],
  };
}

const ORIGIN = metal("Zn", [0, 0, 0]);

describe("polyhedraMeshes geometry", () => {
  it("emits three fresh vertices per face, indexed sequentially", () => {
    const meshes = polyhedraMeshes([tetra(0)], [ORIGIN], [0]);
    expect(meshes.size).toBe(1);
    const mesh = [...meshes.values()][0];
    expect(mesh.vertexArr).toHaveLength(12); // 4 faces x 3, no sharing
    expect(mesh.normalArr).toHaveLength(12);
    expect(mesh.faceArr).toEqual([...Array(12).keys()]);
  });

  it("orients every normal away from the polyhedron centroid", () => {
    const poly = tetra(0);
    const mesh = [...polyhedraMeshes([poly], [ORIGIN], [0]).values()][0];
    const c = [0, 1, 2].map(
      (k) => poly.vertices.reduce((s, v) => s + v[k], 0) / 4,
    );
    for (let f = 0; f < mesh.faceArr.length; f += 3) {
      const tri = [0, 1, 2].map((k) => mesh.vertexArr[mesh.faceArr[f + k]]);
      const n = mesh.normalArr[mesh.faceArr[f]];
      const mid = {
        x: (tri[0].x + tri[1].x + tri[2].x) / 3 - c[0],
        y: (tri[0].y + tri[1].y + tri[2].y) / 3 - c[1],
        z: (tri[0].z + tri[1].z + tri[2].z) / 3 - c[2],
      };
      expect(n.x * mid.x + n.y * mid.y + n.z * mid.z).toBeGreaterThan(0);
    }
  });

  it("winds each emitted triangle right-handed about its own normal", () => {
    // a back-facing winding would cull the face under flat shading
    const mesh = [...polyhedraMeshes([tetra(0)], [ORIGIN], [0]).values()][0];
    for (let f = 0; f < mesh.faceArr.length; f += 3) {
      const [p, q, r] = [0, 1, 2].map(
        (k) => mesh.vertexArr[mesh.faceArr[f + k]],
      );
      const n = mesh.normalArr[mesh.faceArr[f]];
      const u = { x: q.x - p.x, y: q.y - p.y, z: q.z - p.z };
      const v = { x: r.x - p.x, y: r.y - p.y, z: r.z - p.z };
      const cross = {
        x: u.y * v.z - u.z * v.y,
        y: u.z * v.x - u.x * v.z,
        z: u.x * v.y - u.y * v.x,
      };
      expect(
        cross.x * n.x + cross.y * n.y + cross.z * n.z,
      ).toBeGreaterThan(0);
    }
    for (const n of mesh.normalArr) {
      expect(Math.hypot(n.x, n.y, n.z)).toBeCloseTo(1, 12);
    }
  });

  it("is winding-agnostic: a reversed face gives the same normal", () => {
    const fwd = tetra(0);
    const rev: ScenePolyhedron = {
      ...fwd,
      faces: fwd.faces.map(([a, b, c]) => [a, c, b] as [number, number, number]),
    };
    const a = [...polyhedraMeshes([fwd], [ORIGIN], [0]).values()][0];
    const b = [...polyhedraMeshes([rev], [ORIGIN], [0]).values()][0];
    expect(b.normalArr).toEqual(a.normalArr);
  });

  it("drops degenerate faces instead of emitting NaN normals", () => {
    const poly: ScenePolyhedron = {
      metal: 0,
      vertices: [
        [0, 0, 0],
        [1, 0, 0],
        [2, 0, 0], // collinear with the first two
        [0, 1, 0],
      ],
      faces: [
        [0, 1, 2],
        [0, 1, 3],
      ],
    };
    const mesh = [...polyhedraMeshes([poly], [ORIGIN], [0]).values()][0];
    expect(mesh.vertexArr).toHaveLength(3);
    for (const n of mesh.normalArr) {
      expect(Number.isFinite(n.x + n.y + n.z)).toBe(true);
    }
  });
});

describe("polyhedraMeshes color buckets", () => {
  const atoms = [metal("Zn", [0, 0, 0]), metal("Cu", [5, 0, 0])];

  it("buckets bimetallic nodes by the central atom's element", () => {
    const meshes = polyhedraMeshes(
      [tetra(0), tetra(1), tetra(0)],
      atoms,
      [0, 1, 2],
    );
    expect([...meshes.keys()].sort()).toEqual(
      [elementColor("Zn"), elementColor("Cu")].sort(),
    );
    // the two Zn polyhedra share one soup
    expect(meshes.get(elementColor("Zn"))!.vertexArr).toHaveLength(24);
    expect(meshes.get(elementColor("Cu"))!.vertexArr).toHaveLength(12);
  });

  it("still draws a polyhedron whose metal index dangles", () => {
    const meshes = polyhedraMeshes([tetra(99)], atoms, [0]);
    expect(meshes.size).toBe(1);
    expect([...meshes.values()][0].vertexArr).toHaveLength(12);
  });
});

describe("visiblePolyhedra", () => {
  const atoms = [metal("Zn", [0, 0, 0]), metal("Cu", [5, 0, 0])];

  it("keeps scene order and drops hidden metals", () => {
    const polys = [tetra(0), tetra(1), tetra(0)];
    expect(visiblePolyhedra(polys, atoms, (a) => a.elem === "Cu")).toEqual([
      0, 2,
    ]);
    expect(visiblePolyhedra(polys, atoms)).toEqual([0, 1, 2]);
  });

  it("does not let a dangling metal index be filtered out", () => {
    expect(visiblePolyhedra([tetra(99)], atoms, () => true)).toEqual([0]);
  });
});

describe("polyhedraMeshesCached", () => {
  it("is bit-identical to the direct build and hits on repeat calls", () => {
    const atoms = [metal("Zn", [0, 0, 0])];
    const polys = [tetra(0)];
    const direct = polyhedraMeshes(polys, atoms, [0]);
    const first = polyhedraMeshesCached(polys, atoms);
    expect(first).toEqual(direct); // same math, purely a cache
    expect(polyhedraMeshesCached(polys, atoms)).toBe(first); // no re-mesh
  });

  it("keys on the visible set, not on the filter identity", () => {
    const atoms = [metal("Zn", [0, 0, 0]), metal("Cu", [5, 0, 0])];
    const polys = [tetra(0), tetra(1)];
    const all = polyhedraMeshesCached(polys, atoms);
    // a different closure that hides nothing must still hit
    expect(polyhedraMeshesCached(polys, atoms, () => false)).toBe(all);
    const zincOnly = polyhedraMeshesCached(polys, atoms, (a) => a.elem === "Cu");
    expect(zincOnly).not.toBe(all);
    expect([...zincOnly.keys()]).toEqual([elementColor("Zn")]);
    expect(polyhedraMeshesCached(polys, atoms, (a) => a.elem === "Cu")).toBe(
      zincOnly,
    );
  });

  it("evicts old signatures rather than growing without bound", () => {
    const atoms = Array.from({ length: 12 }, (_, i) =>
      metal("Zn", [i, 0, 0]),
    );
    const polys = atoms.map((_, i) => tetra(i));
    const first = polyhedraMeshesCached(polys, atoms, (a) => a.xyz[0] === 0);
    // 6 further distinct visible sets push the first signature out
    for (let k = 1; k <= 6; k += 1) {
      polyhedraMeshesCached(polys, atoms, (a) => a.xyz[0] === k);
    }
    expect(polyhedraMeshesCached(polys, atoms, (a) => a.xyz[0] === 0)).not.toBe(
      first,
    );
  });
});
