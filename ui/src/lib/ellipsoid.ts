/** ORTEP-style ADP ellipsoid meshes for 3Dmol addCustom.
 *
 * The server sends per-atom 50%-probability semi-axis radii r[3] (Å) and a
 * row-major rotation matrix m[9] whose COLUMNS are the principal axes. A
 * unit icosphere is transformed per atom: x' = c + M·diag(r)·u, with
 * normals n' = normalize(M·diag(1/r)·u) (M orthogonal).
 */
import type { SceneAtom } from "./wbTypes";

interface XYZ {
  x: number;
  y: number;
  z: number;
}

export interface CustomMesh {
  vertexArr: XYZ[];
  normalArr: XYZ[];
  faceArr: number[];
}

/** CPK-ish element colors (match 3Dmol's default Jmol scheme closely enough
 * that ellipsoids blend with the stick model). */
const ELEMENT_COLORS: Record<string, string> = {
  H: "#e8e8e8", B: "#ffb5b5", C: "#909090", N: "#3050f8", O: "#ff0d0d",
  F: "#90e050", Na: "#ab5cf2", Mg: "#8aff00", Al: "#bfa6a6", Si: "#f0c8a0",
  P: "#ff8000", S: "#ffff30", Cl: "#1ff01f", K: "#8f40d4", Ca: "#3dff00",
  Ti: "#bfc2c7", V: "#a6a6ab", Cr: "#8a99c7", Mn: "#9c7ac7", Fe: "#e06633",
  Co: "#f090a0", Ni: "#50d050", Cu: "#c88033", Zn: "#7d80b0", Ga: "#c28f8f",
  Ge: "#668f8f", As: "#bd80e3", Se: "#ffa100", Br: "#a62929", Rb: "#702eb0",
  Sr: "#00ff00", Y: "#94ffff", Zr: "#94e0e0", Nb: "#73c2c9", Mo: "#54b5b5",
  Ru: "#248f8f", Rh: "#0a7d8c", Pd: "#006985", Ag: "#c0c0c0", Cd: "#ffd98f",
  In: "#a67573", Sn: "#668080", Sb: "#9e63b5", Te: "#d47a00", I: "#940094",
  Cs: "#57178f", Ba: "#00c900", La: "#70d4ff", Ce: "#ffffc7", Nd: "#c7ffc7",
  Eu: "#61ffc7", Gd: "#45ffc7", Tb: "#30ffc7", Dy: "#1fffc7", Er: "#00e675",
  Yb: "#00bf38", Hf: "#4dc2ff", Ta: "#4da6ff", W: "#2194d6", Re: "#267dab",
  Os: "#266696", Ir: "#175487", Pt: "#d0d0e0", Au: "#ffd123", Hg: "#b8b8d0",
  Tl: "#a6544d", Pb: "#575961", Bi: "#9e4fb5", Th: "#00baff", U: "#008fff",
};

export function elementColor(elem: string): string {
  return ELEMENT_COLORS[elem] ?? "#ff69b4";
}

/** Distinct tints for disorder PART groups shown simultaneously (查看器 P1
 * "同屏异色", Olex2 part colouring). Positive parts walk the palette from
 * the front; negative parts (symmetry-excluded PART -1/-2) from an offset
 * so PART 1 vs PART -1 never collide. */
const PART_COLORS = [
  "#0ea5e9", // sky
  "#f97316", // orange
  "#a855f7", // purple
  "#ec4899", // pink
  "#84cc16", // lime
  "#14b8a6", // teal
];

export function partColor(part: number): string {
  const k = Math.abs(part) - 1 + (part < 0 ? 3 : 0);
  return PART_COLORS[((k % PART_COLORS.length) + PART_COLORS.length) %
    PART_COLORS.length];
}

// ------------------------------------------------------------- unit icosphere
let unitSphere: { verts: number[][]; faces: number[][] } | null = null;

function buildUnitSphere(subdiv: number): { verts: number[][]; faces: number[][] } {
  const t = (1 + Math.sqrt(5)) / 2;
  let verts: number[][] = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ].map((v) => {
    const m = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / m, v[1] / m, v[2] / m];
  });
  let faces: number[][] = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];
  for (let s = 0; s < subdiv; s += 1) {
    const midCache = new Map<string, number>();
    const mid = (a: number, b: number): number => {
      const key = a < b ? `${a}_${b}` : `${b}_${a}`;
      const hit = midCache.get(key);
      if (hit !== undefined) return hit;
      const va = verts[a];
      const vb = verts[b];
      const m = [va[0] + vb[0], va[1] + vb[1], va[2] + vb[2]];
      const len = Math.hypot(m[0], m[1], m[2]);
      verts.push([m[0] / len, m[1] / len, m[2] / len]);
      const idx = verts.length - 1;
      midCache.set(key, idx);
      return idx;
    };
    const next: number[][] = [];
    for (const [a, b, c] of faces) {
      const ab = mid(a, b);
      const bc = mid(b, c);
      const ca = mid(c, a);
      next.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    }
    faces = next;
    verts = verts.slice();
  }
  return { verts, faces };
}

function getUnitSphere(): { verts: number[][]; faces: number[][] } {
  if (!unitSphere) unitSphere = buildUnitSphere(2); // 162 verts / 320 faces
  return unitSphere;
}

const MIN_R = 0.02;

// Rebuilds re-run for reasons that don't change the ellipsoids (H toggle,
// hbonds, PART filter…). Meshing ~10^5 vertices each time is the single
// biggest main-thread cost on big scenes, so memoize per scene identity +
// a signature of (indices, tints). Keyed by the atoms array (WeakMap: frees
// with the scene); a handful of signatures per scene covers toggle churn.
const MESH_CACHE = new WeakMap<
  SceneAtom[],
  Map<string, Map<string, CustomMesh>>
>();
const MESH_CACHE_MAX_SIGS = 6;

export function ellipsoidMeshesCached(
  atoms: SceneAtom[],
  indices: number[],
  colorOverrides?: Map<number, string>,
): Map<string, CustomMesh> {
  const sig =
    indices.join(",") +
    "|" +
    (colorOverrides
      ? [...colorOverrides.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([i, c]) => `${i}:${c}`)
          .join(",")
      : "");
  let perScene = MESH_CACHE.get(atoms);
  if (!perScene) {
    perScene = new Map();
    MESH_CACHE.set(atoms, perScene);
  }
  const hit = perScene.get(sig);
  if (hit) return hit;
  const built = ellipsoidMeshes(atoms, indices, colorOverrides);
  while (perScene.size >= MESH_CACHE_MAX_SIGS) {
    const oldest = perScene.keys().next().value;
    if (oldest === undefined) break;
    perScene.delete(oldest);
  }
  perScene.set(sig, built);
  return built;
}

/** Build one combined mesh per color for the given atom indices; atoms
 * without a usable ell entry are skipped (caller renders them as spheres).
 * colorOverrides (atom index -> css color) wins over the element palette
 * (PART tinting). */
export function ellipsoidMeshes(
  atoms: SceneAtom[],
  indices: number[],
  colorOverrides?: Map<number, string>,
): Map<string, CustomMesh> {
  const sphere = getUnitSphere();
  const out = new Map<string, CustomMesh>();
  for (const idx of indices) {
    const a = atoms[idx];
    const ell = a?.ell;
    if (!a || a.adp_known === false || !ell?.r || !ell.m || ell.npd) continue;
    const [r1, r2, r3] = ell.r;
    const rr = [Math.max(r1, MIN_R), Math.max(r2, MIN_R), Math.max(r3, MIN_R)];
    const m = ell.m;
    const color = colorOverrides?.get(idx) ?? elementColor(a.elem);
    let mesh = out.get(color);
    if (!mesh) {
      mesh = { vertexArr: [], normalArr: [], faceArr: [] };
      out.set(color, mesh);
    }
    const base = mesh.vertexArr.length;
    const [cx, cy, cz] = a.xyz;
    for (const u of sphere.verts) {
      // scaled point s = diag(r)·u ; world x = c + M·s
      const sx = rr[0] * u[0];
      const sy = rr[1] * u[1];
      const sz = rr[2] * u[2];
      mesh.vertexArr.push({
        x: cx + m[0] * sx + m[1] * sy + m[2] * sz,
        y: cy + m[3] * sx + m[4] * sy + m[5] * sz,
        z: cz + m[6] * sx + m[7] * sy + m[8] * sz,
      });
      // normal direction = M·diag(1/r)·u
      const nx0 = u[0] / rr[0];
      const ny0 = u[1] / rr[1];
      const nz0 = u[2] / rr[2];
      let nx = m[0] * nx0 + m[1] * ny0 + m[2] * nz0;
      let ny = m[3] * nx0 + m[4] * ny0 + m[5] * nz0;
      let nz = m[6] * nx0 + m[7] * ny0 + m[8] * nz0;
      const nl = Math.hypot(nx, ny, nz) || 1;
      nx /= nl;
      ny /= nl;
      nz /= nl;
      mesh.normalArr.push({ x: nx, y: ny, z: nz });
    }
    for (const [fa, fb, fc] of sphere.faces) {
      mesh.faceArr.push(base + fa, base + fb, base + fc);
    }
  }
  return out;
}
