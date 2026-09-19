/** Lattice tiling for the scene `range` contract (round-2 R2.2, defect D7).
 *
 * The scene names the integer translations its drawn instances occupy
 * (`range.tiles`); the client instances every PER-CELL product - the void
 * isosurface, the Fo−Fc / 2Fo−Fc density, the Q peaks, the symmetry
 * elements - over them. Before this, all four were drawn in the origin cell
 * whatever slice of the crystal was on screen: a supercell of atoms sat
 * inside a single cell of pore, and a grown fragment reaching into a
 * neighbouring cell had no density there at all.
 *
 * The architecture the contract buys: the heavy per-cell products stay
 * cached per NODE (one marching-cubes mesh, one peak list, one set of
 * symmetry elements) and only the cheap instancing depends on the range.
 * Tiling them server-side would put ~1.4 GB of a 4×4×4 MOF void grid on the
 * wire; re-adding one meshed surface per tile costs ~20 ms each.
 *
 * Pure geometry - no 3Dmol, no React.
 */
import { cellVectors, type Vec3 } from "./cellMath";
import type { SceneCell } from "./wbTypes";

/** Drawing budget, mirroring the server's `scene.MAX_TILES`. */
export const MAX_TILES = 64;

/** The range of a scene cached before the contract existed: the origin cell
 * alone, i.e. exactly what the viewer used to hard-code. Frozen and shared
 * so it can be used as a stable prop identity. */
export const ORIGIN_TILES: readonly Vec3[] = Object.freeze([
  Object.freeze([0, 0, 0]) as unknown as Vec3,
]);

// Defensive bound on the SCAN (never on the reported tile count), mirroring
// the server's `_TILE_SCAN_CAP` / `_TILE_SCAN_WINDOW`: a bounding box may in
// principle span thousands of cells per axis, and enumerating that product
// is pointless when at most `max` tiles survive.
const SCAN_CAP = 4096;
const SCAN_WINDOW = 15;

export function isOriginTile(t: Vec3): boolean {
  return t[0] === 0 && t[1] === 0 && t[2] === 0;
}

function lexLess(a: Vec3, b: Vec3): number {
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}

/** Every integer translation whose unit box [t, t+1)³ meets the fractional
 * box [lo, hi] - the same rule the server applies to the drawn instances,
 * so a client that has to derive its own range agrees with one that was
 * given one. Lexicographically sorted. Axes with hi < lo are tolerated
 * (ordered per axis); a non-finite bound falls back to the origin tile.
 *
 * Capped at `max` by `centreMostTiles` around the box MIDPOINT - the server,
 * which has the instances, ranks by their centroid instead.
 */
export function tilesForRange(lo: Vec3, hi: Vec3, max = MAX_TILES): Vec3[] {
  const tLo: number[] = [];
  const tHi: number[] = [];
  for (let k = 0; k < 3; k += 1) {
    const a = lo[k];
    const b = hi[k];
    if (!Number.isFinite(a) || !Number.isFinite(b)) return [[0, 0, 0]];
    tLo.push(Math.floor(Math.min(a, b)));
    tHi.push(Math.floor(Math.max(a, b)));
  }
  const centre: Vec3 = [
    (Math.min(lo[0], hi[0]) + Math.max(lo[0], hi[0])) / 2,
    (Math.min(lo[1], hi[1]) + Math.max(lo[1], hi[1])) / 2,
    (Math.min(lo[2], hi[2]) + Math.max(lo[2], hi[2])) / 2,
  ];
  let n = 1;
  for (let k = 0; k < 3; k += 1) n *= tHi[k] - tLo[k] + 1;
  const sLo = [...tLo];
  const sHi = [...tHi];
  if (n > SCAN_CAP) {
    const half = Math.floor(SCAN_WINDOW / 2);
    for (let k = 0; k < 3; k += 1) {
      const c = Math.floor(centre[k]);
      sLo[k] = Math.max(tLo[k], c - half);
      sHi[k] = Math.min(tHi[k], c + half);
    }
  }
  const out: Vec3[] = [];
  for (let ta = sLo[0]; ta <= sHi[0]; ta += 1) {
    for (let tb = sLo[1]; tb <= sHi[1]; tb += 1) {
      for (let tc = sLo[2]; tc <= sHi[2]; tc += 1) out.push([ta, tb, tc]);
    }
  }
  // the triple loop already emits lexicographic order
  return out.length > max ? centreMostTiles(out, centre, max) : out;
}

/** The `cap` tiles whose box centre lies nearest `centreFrac`, returned
 * lexicographically sorted - deterministic (ties break on the tile triple,
 * after rounding the squared distance so float noise cannot split a
 * symmetric pair) and independent of the input order.
 *
 * Ranks in FRACTIONAL space, which is metric-free; the server's truncation
 * (Cartesian distance to `range.centre_cart`) is the authoritative one and
 * the two agree for any cell with equal axes. This runs only where the
 * client derives a range itself, never on a list the server already sent.
 */
export function centreMostTiles(
  tiles: readonly Vec3[],
  centreFrac: Vec3,
  cap: number,
): Vec3[] {
  const sorted = [...tiles];
  if (sorted.length <= cap) return sorted.sort(lexLess);
  const d2 = (t: Vec3): number => {
    const dx = t[0] + 0.5 - centreFrac[0];
    const dy = t[1] + 0.5 - centreFrac[1];
    const dz = t[2] + 0.5 - centreFrac[2];
    return Math.round((dx * dx + dy * dy + dz * dz) * 1e6) / 1e6;
  };
  sorted.sort((a, b) => d2(a) - d2(b) || lexLess(a, b));
  return sorted.slice(0, cap).sort(lexLess);
}

/** Cartesian translation of each tile: t·a + t·b + t·c through the same
 * orthogonalization the scene's atom coordinates use. */
export function tileOffsetsCart(
  cell: SceneCell,
  tiles: readonly Vec3[],
): Vec3[] {
  const [va, vb, vc] = cellVectors(cell);
  return tiles.map((t) => [
    t[0] * va[0] + t[1] * vb[0] + t[2] * vc[0],
    t[0] * va[1] + t[1] * vb[1] + t[2] * vc[1],
    t[0] * va[2] + t[1] * vb[2] + t[2] * vc[2],
  ] as Vec3);
}
