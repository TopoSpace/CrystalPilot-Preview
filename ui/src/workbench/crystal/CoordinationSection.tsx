/** 配位环境 (P4): derived client-side from the current scene (atoms+bonds).
 *
 * Metal = the server's verdict (`atom.m`, chem.bonding's periodic-table
 * whitelist, D9); the client never decides metal-ness from the element
 * symbol. The bond kind code (scene.bonds[k][2]: 0 covalent / 1
 * coordination / 2 eta / 3 metal-metal) decides what counts: an eta-bound
 * ring counts once, as ONE ligand (its atoms are grouped through their
 * covalent bonds, so ferrocene is CN 2), a metal-metal edge is a contact
 * and never a ligand. CN counts bonds incident to the metal (symmetry
 * copies included - bridging bonds close through them); rows are shown only
 * for non-sym metals so each crystallographic atom appears once. Clicking a
 * row selects the atom (structure-tab selection card + viewer highlight).
 */
import { useMemo } from "react";
import { cx } from "../../lib/format";
import type { SceneAtom, SceneResponse } from "../../lib/wbTypes";
import { t } from "../../lib/i18n";
import { useCrystal } from "../../state/CrystalProvider";

export const BOND_COVALENT = 0;
export const BOND_COORDINATION = 1;
export const BOND_ETA = 2;
export const BOND_METAL_METAL = 3;

const normElem = (e: string): string =>
  e.length === 0 ? e : e[0].toUpperCase() + e.slice(1).toLowerCase();

/** Metal-ness comes from the server (chem.bonding), never from a list. */
export const isMetalAtom = (a: SceneAtom): boolean => a.m === true;

export interface CoordinationRow {
  /** index into scene.atoms */
  index: number;
  label: string;
  elem: string;
  /** ligand count: donor atoms + one per eta-bound ring. */
  cn: number;
  minD: number;
  maxD: number;
  /** "O8" / "O6N2" - donor element counts sorted descending. */
  ligands: string;
  /** eta-bound rings (each counted once in cn). */
  etaRings: number;
  /** metal–metal contacts in the bond list (cluster edges), not in cn. */
  metalContacts: number;
}

function dist(a: [number, number, number], b: [number, number, number]): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/** Number of connected groups among `members` under the covalent graph:
 * the eta-ring instances a metal's eta edges belong to. */
export function countGroups(members: number[], covalent: Set<number>[]): number {
  const left = new Set(members);
  let groups = 0;
  while (left.size > 0) {
    const seed = left.values().next().value as number;
    left.delete(seed);
    groups += 1;
    const stack = [seed];
    while (stack.length > 0) {
      const u = stack.pop() as number;
      for (const v of covalent[u] ?? []) {
        if (left.has(v)) {
          left.delete(v);
          stack.push(v);
        }
      }
    }
  }
  return groups;
}

export function deriveCoordination(scene: SceneResponse, selectedIndex?: number): CoordinationRow[] {
  const { atoms, bonds } = scene;
  const alive = (i: number): boolean =>
    atoms[i] !== undefined && atoms[i].flag !== "removed";
  // adjacency over live atoms, with the bond kind; covalent graph apart
  // (it groups eta ring atoms into ring instances)
  const nbrs: { j: number; kind: number }[][] = atoms.map(() => []);
  const covalent: Set<number>[] = atoms.map(() => new Set<number>());
  for (const b of bonds) {
    const [i, j] = b;
    const kind = b[2] ?? BOND_COVALENT;
    if (!alive(i) || !alive(j)) continue;
    nbrs[i].push({ j, kind });
    nbrs[j].push({ j: i, kind });
    if (kind === BOND_COVALENT) {
      covalent[i].add(j);
      covalent[j].add(i);
    }
  }
  const rows: CoordinationRow[] = [];
  for (let i = 0; i < atoms.length; i += 1) {
    const a = atoms[i];
    if ((a.sym && i !== selectedIndex) || !alive(i) || !isMetalAtom(a)) continue;
    const ns = nbrs[i];
    if (ns.length === 0) continue;
    const byElem = new Map<string, number>();
    let minD = Infinity;
    let maxD = -Infinity;
    let cn = 0;
    let metalContacts = 0;
    const etaAtoms: number[] = [];
    for (const { j, kind } of ns) {
      const b = atoms[j];
      if (kind === BOND_METAL_METAL || isMetalAtom(b)) {
        // cluster M–M edge (e.g. Zr…Zr in a Zr6 node): a real contact but
        // not a donor - kept out of CN / bond-length range
        metalContacts += 1;
        continue;
      }
      if (kind === BOND_ETA) {
        etaAtoms.push(j);
        continue;
      }
      cn += 1;
      const el = normElem(b.elem);
      byElem.set(el, (byElem.get(el) ?? 0) + 1);
      const d = dist(a.xyz, b.xyz);
      if (d < minD) minD = d;
      if (d > maxD) maxD = d;
    }
    const etaRings = countGroups(etaAtoms, covalent);
    cn += etaRings;
    if (cn === 0 && metalContacts === 0) continue;
    const ligands = [...byElem.entries()]
      .sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
      .map(([el, n]) => `${el}${n > 1 ? n : ""}`)
      .join("");
    rows.push({
      index: i,
      label: a.label,
      elem: normElem(a.elem),
      cn,
      minD,
      maxD,
      ligands,
      etaRings,
      metalContacts,
    });
  }
  rows.sort((x, y) => x.label.localeCompare(y.label, undefined, { numeric: true }));
  return rows;
}

export function CoordinationSection() {
  const { state, locate } = useCrystal();
  const scene = state.sceneNode === state.viewNode ? state.scene : null;
  const selectedIndex = state.selection?.index;
  const rows = useMemo(
    () => (scene === null ? [] : deriveCoordination(scene, selectedIndex)),
    [scene, selectedIndex],
  );

  if (scene === null || state.sceneStatus !== "ok") return <p className="px-3 py-2 text-xs text-ink-3">{t.crystal.coordUnavailable}</p>;

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-2 px-3 pt-1 pb-1">
        <span className="text-2xs font-medium text-ink-3">
          {t.coordTitle}
        </span>
        {rows.length > 0 && (
          <span className="text-2xs text-ink-3">{t.coordHint}</span>
        )}
      </div>
      {rows.length === 0 ? (
        <div className="px-3 pb-2 text-2xs text-ink-3">{t.coordNone}</div>
      ) : (
        <div className="px-3 pb-1">
          {scene.mode === "asu" && (
            <div className="pb-1 text-2xs leading-snug text-ink-3">
              {t.coordAsuCaveat}
            </div>
          )}
          <p className="pb-1 text-xs text-ink-3">{t.crystal.coordDisplayOnly}</p>
          {scene.meta.truncated && <p className="pb-1 text-xs text-warn">{t.crystal.coordTruncated}</p>}
          <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-xs tabular-nums">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="py-1 pr-2 font-medium">{t.coordMetal}</th>
                <th className="py-1 pr-2 text-right font-medium">
                  {t.coordCN}
                </th>
                <th className="py-1 pr-2 text-right font-medium">
                  {t.coordRange}
                </th>
                <th className="py-1 text-right font-medium">
                  {t.coordLigands}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.index}
                  data-testid="coordination-row"
                  className={cx(
                    "border-t border-line/60 transition-colors",
                    r.index === selectedIndex
                      ? "bg-accent/8 text-ink"
                      : "text-ink-2 hover:bg-raised/40",
                  )}
                >
                  <td className="py-1 pr-2 font-semibold text-ink">
                    <button type="button" aria-label={t.crystal.coordLocateAria(r.label)} aria-pressed={r.index === selectedIndex}
                      title={scene.atoms[r.index].symop ?? "x,y,z"}
                      onClick={() => locate(scene.node, { atom: scene.atoms[r.index], index: r.index })}
                      className="rounded py-1 text-left hover:text-accent focus-visible:outline-2 focus-visible:outline-accent">
                      {r.label}{scene.atoms[r.index].sym ? t.crystal.coordSymImage : ""}
                    </button>
                  </td>
                  <td className="py-1 pr-2 text-right">{r.cn}</td>
                  <td className="py-1 pr-2 text-right">
                    {!Number.isFinite(r.minD)
                      ? "—"
                      : `${r.minD.toFixed(2)}–${r.maxD.toFixed(2)}`}
                  </td>
                  <td className="py-1 text-right">
                    {r.ligands || (r.etaRings === 0 ? "—" : "")}
                    {r.etaRings > 0 && (
                      <span
                        className="text-ink-2"
                        title={t.crystal.coordEtaTip(r.etaRings)}
                      >
                        {r.ligands ? " " : ""}
                        η×{r.etaRings}
                      </span>
                    )}
                    {r.metalContacts > 0 && (
                      <span
                        className="text-ink-3"
                        title={t.crystal.coordMetalContactsTip(r.metalContacts)}
                      >
                        {" "}
                        +{r.metalContacts}M
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  );
}
