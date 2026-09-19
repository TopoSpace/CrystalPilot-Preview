/** Viewer capability thresholds.
 *
 * Deliberately free of any 3Dmol import: CrystalViewer is lazy-loaded into
 * its own chunk (vite.config chunkSizeWarningLimit), so the toolbar cannot
 * read a threshold straight off CrystalViewer.tsx without dragging 3Dmol
 * into the main bundle.
 */

/** Above this atom count the viewer drops ADP ellipsoids back to
 * ball-and-stick and stops drawing per-atom labels - meshing and labelling
 * a supercell costs more than the detail is worth. The fallback is silent
 * in the scene itself, so anything that renders the 椭球 / 标签 controls
 * has to compare `scene.atoms.length` against this to avoid showing them
 * as active. (Per-polyhedron CN labels are NOT capped.) */
export const MAX_ELLIPSOID_ATOMS = 1500;

/** Independent per-layer budgets. The scene range itself is separately
 * bounded to MAX_TILES in lib/tiles.ts. */
export const MAX_SYMMETRY_TILES = 8;
export const MAX_Q_PEAK_SPHERES = 3000;

export interface QPeakDrawPlan {
  peaksPerTile: number;
  tileCount: number;
  sphereCount: number;
}

/** Keep Q-peak copies within their absolute shape budget, including the
 * unusual case where one cell already contains more peaks than the budget. */
export function qPeakDrawPlan(positivePeaks: number, availableTiles: number): QPeakDrawPlan {
  const peaksPerTile = Math.min(
    MAX_Q_PEAK_SPHERES,
    Math.max(0, Math.floor(Number.isFinite(positivePeaks) ? positivePeaks : 0)),
  );
  const tiles = Math.max(0, Math.floor(Number.isFinite(availableTiles) ? availableTiles : 0));
  if (peaksPerTile === 0 || tiles === 0) {
    return { peaksPerTile, tileCount: 0, sphereCount: 0 };
  }
  const tileCount = Math.min(tiles, Math.floor(MAX_Q_PEAK_SPHERES / peaksPerTile));
  return { peaksPerTile, tileCount, sphereCount: peaksPerTile * tileCount };
}

export interface OverlayCoverage {
  symmetry: { drawnTiles: number; requestedTiles: number };
  peaks: { drawnSpheres: number; requestedSpheres: number };
}

/** Requested-vs-drawn counts for the two independently capped layers.
 * `availableTiles` is the server-supplied (at most 64) centre set, while
 * `requestedTiles` is the uncapped range count. */
export function overlayCoverage(
  requestedTiles: number,
  availableTiles: number,
  positivePeaks: number,
): OverlayCoverage {
  const requested = Math.max(0, Math.floor(Number.isFinite(requestedTiles) ? requestedTiles : 0));
  const available = Math.min(
    requested,
    Math.max(0, Math.floor(Number.isFinite(availableTiles) ? availableTiles : 0)),
  );
  const positive = Math.max(0, Math.floor(Number.isFinite(positivePeaks) ? positivePeaks : 0));
  const peakPlan = qPeakDrawPlan(positive, available);
  return {
    symmetry: {
      drawnTiles: Math.min(available, MAX_SYMMETRY_TILES),
      requestedTiles: requested,
    },
    peaks: {
      drawnSpheres: peakPlan.sphereCount,
      requestedSpheres: requested * positive,
    },
  };
}

export interface ViewerDepthApi {
  enableFog: (fog: false | { fogStart: number; fogEnd: number }) => unknown;
  setSlab: (near: number, far: number) => unknown;
}

/** A rotation-safe span, including an older camera centre retained after a
 * node change. getView's first three values translate model coordinates. */
export function atomDepthSpan(
  atoms: readonly { xyz: readonly number[] }[],
  modelTranslation?: readonly number[],
): number {
  if (atoms.length === 0) return 5;
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (const atom of atoms) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = atom.xyz[axis];
      if (!Number.isFinite(value)) continue;
      lo[axis] = Math.min(lo[axis], value);
      hi[axis] = Math.max(hi[axis], value);
    }
  }
  const diagonal = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
  let fromCentre = 0;
  if (modelTranslation && modelTranslation.length >= 3 && modelTranslation.slice(0, 3).every(Number.isFinite)) {
    fromCentre = Math.hypot(...lo.map((low, axis) =>
      Math.max(Math.abs(low + modelTranslation[axis]), Math.abs(hi[axis] + modelTranslation[axis])),
    )) + 5;
  }
  return Number.isFinite(diagonal) && Number.isFinite(fromCentre)
    ? Math.max(5, diagonal, fromCentre)
    : 5;
}

/** Apply camera depth through 3Dmol's public API. Fog is off by default;
 * clip=1 is a permissive full-atom span rather than zoomTo's asymmetric
 * slab, so subsequent rotate/zoom operations cannot lose the back half. */
export function applyViewerDepth(
  viewer: ViewerDepthApi,
  depth: { fog: boolean; fogStart: number; clip: number },
  fullSpan: number,
): void {
  const fogStart = Math.max(0.2, Math.min(0.9, Number.isFinite(depth.fogStart) ? depth.fogStart : 0.55));
  const clip = Math.max(0.1, Math.min(1, Number.isFinite(depth.clip) ? depth.clip : 1));
  viewer.enableFog(depth.fog ? { fogStart, fogEnd: 1 } : false);
  const halfSpan = Math.max(1, (Number.isFinite(fullSpan) ? fullSpan : 5) * clip);
  viewer.setSlab(-halfSpan, halfSpan);
}
