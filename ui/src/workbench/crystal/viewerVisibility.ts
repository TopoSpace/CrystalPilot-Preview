import { fracCoord, fracRows, type Vec3 } from "../../lib/cellMath";
import type { SceneAtom, SceneResponse } from "../../lib/wbTypes";

type Slab = { axis: 0 | 1 | 2; center: number; thickness: number } | null;

export function partHiddenOf(atom: SceneAtom, partFilter: number | null): boolean {
  return partFilter !== null && (atom.part ?? 0) !== 0 && atom.part !== partFilter;
}

export function slabHiddenOf(atom: SceneAtom, slab: Slab, rows: [Vec3, Vec3, Vec3] | null): boolean {
  if (!slab || !rows) return false;
  const fractional = fracCoord(rows, slab.axis, atom.xyz);
  const wrapped = ((fractional % 1) + 1) % 1;
  let distance = Math.abs(wrapped - slab.center);
  distance = Math.min(distance, 1 - distance);
  return distance > slab.thickness / 2;
}

/** The renderer's visibility filters, not a new scientific atom/model count. */
export function drawnAtomCount(scene: SceneResponse, hiddenElems: readonly string[], partFilter: number | null, slab: Slab): number {
  const rows = slab ? fracRows(scene.cell) : null;
  return scene.atoms.filter((atom) => !hiddenElems.includes(atom.elem)
    && !partHiddenOf(atom, partFilter) && !slabHiddenOf(atom, slab, rows)).length;
}
