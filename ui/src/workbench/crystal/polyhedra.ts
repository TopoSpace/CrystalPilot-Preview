/** Coordination-polyhedron meshes for 3Dmol addCustom.
 *
 * One flat-shaded triangle soup per metal ELEMENT (P2-1: bimetallic MOF
 * nodes stay distinguishable, Diamond convention = central-atom color).
 * Vertices are duplicated per face so every triangle carries its own
 * normal, oriented outward from that polyhedron's centroid.
 */
import { elementColor, type CustomMesh } from "../../lib/ellipsoid";
import type { SceneAtom, ScenePolyhedron } from "../../lib/wbTypes";

/** fallback bucket for a polyhedron whose metal index doesn't resolve */
const POLY_COLOR = "#38bdf8";

/** Polyhedra whose metal is currently drawn, in scene order. A dangling
 * metal index survives the filter - it still renders, in POLY_COLOR. */
export function visiblePolyhedra(
  polyhedra: ScenePolyhedron[],
  atoms: SceneAtom[],
  metalHidden?: (a: SceneAtom) => boolean,
): number[] {
  const out: number[] = [];
  for (let i = 0; i < polyhedra.length; i += 1) {
    const m = atoms[polyhedra[i].metal];
    if (m && metalHidden?.(m)) continue;
    out.push(i);
  }
  return out;
}

/** Build one combined mesh per color for the listed polyhedron indices. */
export function polyhedraMeshes(
  polyhedra: ScenePolyhedron[],
  atoms: SceneAtom[],
  indices: number[],
): Map<string, CustomMesh> {
  const out = new Map<string, CustomMesh>();
  for (const pi of indices) {
    const poly = polyhedra[pi];
    if (!poly) continue;
    const elem = atoms[poly.metal]?.elem;
    const color = elem ? elementColor(elem) : POLY_COLOR;
    let mesh = out.get(color);
    if (!mesh) {
      mesh = { vertexArr: [], normalArr: [], faceArr: [] };
      out.set(color, mesh);
    }
    const { vertexArr, normalArr, faceArr } = mesh;
    const verts = poly.vertices;
    const n = verts.length;
    if (n === 0) continue;
    const c = [0, 1, 2].map(
      (k) => verts.reduce((s, p) => s + p[k], 0) / n,
    ) as [number, number, number];
    for (const [ia, ib, ic] of poly.faces) {
      const a = verts[ia];
      const b = verts[ib];
      const d = verts[ic];
      if (!a || !b || !d) continue;
      const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
      const v = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
      let nrm = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
      ];
      const mag = Math.hypot(nrm[0], nrm[1], nrm[2]);
      if (mag < 1e-9) continue;
      // orient away from the polyhedron centroid
      const centre = [
        (a[0] + b[0] + d[0]) / 3,
        (a[1] + b[1] + d[1]) / 3,
        (a[2] + b[2] + d[2]) / 3,
      ];
      const dot =
        nrm[0] * (centre[0] - c[0]) +
        nrm[1] * (centre[1] - c[1]) +
        nrm[2] * (centre[2] - c[2]);
      let tri: [number, number, number][] = [a, b, d];
      if (dot < 0) {
        nrm = [-nrm[0], -nrm[1], -nrm[2]];
        tri = [a, d, b];
      }
      // |nrm| is unchanged by the flip, so the pre-flip magnitude still
      // normalizes it
      const nn = {
        x: nrm[0] / mag,
        y: nrm[1] / mag,
        z: nrm[2] / mag,
      };
      for (const p of tri) {
        faceArr.push(vertexArr.length);
        vertexArr.push({ x: p[0], y: p[1], z: p[2] });
        normalArr.push(nn);
      }
    }
  }
  return out;
}

// The scene rebuild re-runs for reasons that never touch the polyhedra (H
// toggle, hbonds, ellipsoids, pub style, theme…), and a MOF supercell is
// thousands of triangles - cross products, centroid orientation and
// duplicated vertices for each. Memoize per scene identity + the set of
// visible polyhedra, exactly as lib/ellipsoid.ts caches ADP meshes.
// Keyed by the atoms array (WeakMap: entries free with the scene);
// `polyhedra` always arrives in the same SceneResponse, so it cannot drift
// away from the key.
const MESH_CACHE = new WeakMap<
  SceneAtom[],
  Map<string, Map<string, CustomMesh>>
>();
const MESH_CACHE_MAX_SIGS = 6;

export function polyhedraMeshesCached(
  polyhedra: ScenePolyhedron[],
  atoms: SceneAtom[],
  metalHidden?: (a: SceneAtom) => boolean,
): Map<string, CustomMesh> {
  const indices = visiblePolyhedra(polyhedra, atoms, metalHidden);
  const sig = `${polyhedra.length}|${indices.join(",")}`;
  let perScene = MESH_CACHE.get(atoms);
  if (!perScene) {
    perScene = new Map();
    MESH_CACHE.set(atoms, perScene);
  }
  const hit = perScene.get(sig);
  if (hit) return hit;
  const built = polyhedraMeshes(polyhedra, atoms, indices);
  while (perScene.size >= MESH_CACHE_MAX_SIGS) {
    const oldest = perScene.keys().next().value;
    if (oldest === undefined) break;
    perScene.delete(oldest);
  }
  perScene.set(sig, built);
  return built;
}
