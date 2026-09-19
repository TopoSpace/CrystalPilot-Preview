/** Unit-cell geometry: fractional→Cartesian orthogonalization and the 12 cell
 * edges for drawing a wireframe box.
 *
 * Convention matches cctbx's default orthogonalization (a along x, b in the
 * xy plane), which is what the scene endpoint uses for atom coordinates - so
 * the drawn box lines up with the atoms.
 */
import type { SceneCell } from "./wbTypes";

export type Vec3 = [number, number, number];

const DEG = Math.PI / 180;

/** Column vectors of the orthogonalization matrix: Cartesian a, b, c. */
export function cellVectors(cell: SceneCell): [Vec3, Vec3, Vec3] {
  const { a, b, c } = cell;
  const ca = Math.cos(cell.alpha * DEG);
  const cb = Math.cos(cell.beta * DEG);
  const cg = Math.cos(cell.gamma * DEG);
  const sg = Math.sin(cell.gamma * DEG);
  const va: Vec3 = [a, 0, 0];
  const vb: Vec3 = [b * cg, b * sg, 0];
  const cx = c * cb;
  const cy = (c * (ca - cb * cg)) / sg;
  const cz2 = c * c - cx * cx - cy * cy;
  const vc: Vec3 = [cx, cy, cz2 > 0 ? Math.sqrt(cz2) : 0];
  return [va, vb, vc];
}

/** Cartesian→fractional: rows of the inverse orthogonalization matrix.
 * The frac→cart matrix is upper-triangular-ish by construction (a along x,
 * b in xy), so invert the general 3×3 built from the column vectors. */
export function fracRows(cell: SceneCell): [Vec3, Vec3, Vec3] {
  const [va, vb, vc] = cellVectors(cell);
  // matrix M with columns va|vb|vc; return rows of M^-1
  const m = [
    va[0], vb[0], vc[0],
    va[1], vb[1], vc[1],
    va[2], vb[2], vc[2],
  ];
  const det =
    m[0] * (m[4] * m[8] - m[5] * m[7]) -
    m[1] * (m[3] * m[8] - m[5] * m[6]) +
    m[2] * (m[3] * m[7] - m[4] * m[6]);
  const d = det !== 0 ? 1 / det : 0;
  return [
    [
      (m[4] * m[8] - m[5] * m[7]) * d,
      (m[2] * m[7] - m[1] * m[8]) * d,
      (m[1] * m[5] - m[2] * m[4]) * d,
    ],
    [
      (m[5] * m[6] - m[3] * m[8]) * d,
      (m[0] * m[8] - m[2] * m[6]) * d,
      (m[2] * m[3] - m[0] * m[5]) * d,
    ],
    [
      (m[3] * m[7] - m[4] * m[6]) * d,
      (m[1] * m[6] - m[0] * m[7]) * d,
      (m[0] * m[4] - m[1] * m[3]) * d,
    ],
  ];
}

/** One fractional coordinate (axis 0|1|2) of a Cartesian point. */
export function fracCoord(
  rows: [Vec3, Vec3, Vec3],
  axis: 0 | 1 | 2,
  xyz: [number, number, number],
): number {
  const r = rows[axis];
  return r[0] * xyz[0] + r[1] * xyz[1] + r[2] * xyz[2];
}

function add(...vs: Vec3[]): Vec3 {
  const out: Vec3 = [0, 0, 0];
  for (const v of vs) {
    out[0] += v[0];
    out[1] += v[1];
    out[2] += v[2];
  }
  return out;
}

/** The 8 corners of the (0,0,0)…(1,1,1) cell in Cartesian Å, indexed by the
 * binary triple (i,j,k) → i*4 + j*2 + k. */
export function cellCorners(cell: SceneCell): Vec3[] {
  const [va, vb, vc] = cellVectors(cell);
  const zero: Vec3 = [0, 0, 0];
  const corners: Vec3[] = [];
  for (const i of [0, 1]) {
    for (const j of [0, 1]) {
      for (const k of [0, 1]) {
        corners.push(add(i ? va : zero, j ? vb : zero, k ? vc : zero));
      }
    }
  }
  return corners;
}

/** The 12 edges of the unit-cell box as Cartesian start/end pairs. */
export function cellEdges(cell: SceneCell): Array<[Vec3, Vec3]> {
  const c = cellCorners(cell);
  const idx = (i: number, j: number, k: number) => i * 4 + j * 2 + k;
  const edges: Array<[Vec3, Vec3]> = [];
  for (const i of [0, 1]) {
    for (const j of [0, 1]) {
      for (const k of [0, 1]) {
        // connect each corner to its +1 neighbours (each edge added once)
        if (i === 0) edges.push([c[idx(0, j, k)], c[idx(1, j, k)]]);
        if (j === 0) edges.push([c[idx(i, 0, k)], c[idx(i, 1, k)]]);
        if (k === 0) edges.push([c[idx(i, j, 0)], c[idx(i, j, 1)]]);
      }
    }
  }
  return edges;
}
