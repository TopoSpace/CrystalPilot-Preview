/** Node-tree model (round-3 R2-B): rows that fold, lanes that pack, and the
 * three marks a reader asks for - 当前查看 / 已交付 / 树内最佳 - plus where a
 * node's R1 comes from when the node itself was never refined. Pure, so
 * the panel's behaviour is testable without rendering.
 *
 * Why it exists: the 2026-09-05 review of the Zr-MOF demo (225 nodes, 28
 * branches, 6 of them diag/*) found a flat newest-first list with a 28-lane
 * graph wider than the pane, a compare table of em-dashes (branch heads
 * that were not refine nodes carried no metrics) and no way to tell which
 * node a delivery came from. */
import type { DeliveryMark, RefineNode } from "./wbTypes";

export const DIAG_PREFIX = "diag/";

/** Throw-away branches the batch tools create (ghost_test / element_scan /
 * probe_site keep their candidates on diag/<tool>/<baseline>/<candidate>). */
export function isDiagBranch(name: string): boolean {
  return name.startsWith(DIAG_PREFIX);
}

export type TreeRow =
  | { kind: "node"; node: RefineNode }
  | { kind: "branch"; branch: string; head: RefineNode; count: number; folded: boolean }
  | { kind: "diag"; branches: number; nodes: number; folded: boolean };

export interface FoldState {
  /** per-branch override; absent = the default (diag/* folded, others open) */
  branches: ReadonlyMap<string, boolean>;
  /** the whole diag/* family behind one row */
  diag: boolean;
}

export function isFolded(branch: string, folds: FoldState): boolean {
  return folds.branches.get(branch) ?? isDiagBranch(branch);
}

export function branchOfRow(row: TreeRow): string | null {
  if (row.kind === "node") return row.node.branch;
  if (row.kind === "branch") return row.branch;
  return null;
}

/** Rows, newest first. Every branch gets a header row above its newest
 * visible node; a folded branch is only its header. The diag/* family gets
 * one row at the place of its newest node: while `folds.diag` holds it
 * stands in for every diag branch, otherwise it heads them. */
export function treeRows(nodes: readonly RefineNode[], folds: FoldState): TreeRow[] {
  const rows: TreeRow[] = [];
  const counts = new Map<string, number>();
  for (const n of nodes) counts.set(n.branch, (counts.get(n.branch) ?? 0) + 1);
  const seen = new Set<string>();
  let diagEmitted = false;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (isDiagBranch(n.branch)) {
      if (!diagEmitted) {
        diagEmitted = true;
        const diagBranches = [...counts.keys()].filter(isDiagBranch);
        rows.push({
          kind: "diag",
          branches: diagBranches.length,
          nodes: diagBranches.reduce((a, b) => a + (counts.get(b) ?? 0), 0),
          folded: folds.diag,
        });
      }
      if (folds.diag) continue;
    }
    if (!seen.has(n.branch)) {
      seen.add(n.branch);
      rows.push({
        kind: "branch",
        branch: n.branch,
        head: n,
        count: counts.get(n.branch) ?? 1,
        folded: isFolded(n.branch, folds),
      });
    }
    if (isFolded(n.branch, folds)) continue;
    rows.push({ kind: "node", node: n });
  }
  return rows;
}

// ------------------------------------------------------------------ metrics

export interface MetricsView {
  r1: number | null;
  wr2: number | null;
  goof: number | null;
  /** the node's own refinement produced these numbers */
  current: boolean;
  /** ancestor the numbers are carried from (null when current or unknown) */
  source: string | null;
}

/** A node's R1 and where it comes from: its own refinement, or the nearest
 * refined ancestor (shown as 沿用 nXXXX), or nothing. The node store copies
 * the lineage's last metrics onto every node with metrics_current=false;
 * the reader still needs to know WHICH node earned them. */
export function metricsView(byId: ReadonlyMap<string, RefineNode>, id: string): MetricsView {
  const self = byId.get(id);
  let cur = self ?? null;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    if (cur.metrics_current && cur.r1 !== null) {
      return {
        r1: cur.r1,
        wr2: cur.wr2,
        goof: cur.goof,
        current: cur.id === id,
        source: cur.id === id ? null : cur.id,
      };
    }
    cur = cur.parent !== null ? (byId.get(cur.parent) ?? null) : null;
  }
  return {
    r1: self?.r1 ?? null,
    wr2: self?.wr2 ?? null,
    goof: self?.goof ?? null,
    current: false,
    source: null,
  };
}

/** The refined node with the lowest R1 in the tree (ties: the newest),
 * diagnostic branches excluded - a probe candidate that happens to fit is
 * not "the best model". null when nothing has been refined. */
export function bestNodeId(nodes: readonly RefineNode[]): string | null {
  let best: RefineNode | null = null;
  for (const n of nodes) {
    if (!n.metrics_current || n.r1 === null || isDiagBranch(n.branch)) continue;
    if (best === null || n.r1 <= best.r1!) best = n;
  }
  return best?.id ?? null;
}

export function deliveriesByNode(marks: readonly DeliveryMark[]): Map<string, DeliveryMark[]> {
  const out = new Map<string, DeliveryMark[]>();
  for (const m of marks) {
    const list = out.get(m.node) ?? [];
    list.push(m);
    out.set(m.node, list);
  }
  return out;
}

// -------------------------------------------------------------------- lanes

export interface Fork {
  branch: string;
  /** row index the curve leaves (the branch's bottom row) */
  from: number;
  /** row index it lands on (the parent's row, or the folded row standing in for it) */
  to: number;
  toBranch: string | null;
}

/** The row a node id resolves to on screen: its own row, else the header of
 * its folded branch, else the diag family row; null when nothing shows it. */
export function anchorRow(
  rows: readonly TreeRow[],
  byId: ReadonlyMap<string, RefineNode>,
  id: string,
): number | null {
  const node = byId.get(id);
  if (!node) return null;
  let branchRow: number | null = null;
  let diagRow: number | null = null;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.kind === "node" && r.node.id === id) return i;
    if (r.kind === "branch" && r.branch === node.branch && branchRow === null) branchRow = i;
    if (r.kind === "diag" && diagRow === null) diagRow = i;
  }
  if (branchRow !== null) return branchRow;
  return isDiagBranch(node.branch) ? diagRow : null;
}

/** Fork curves: each visible branch's oldest member joins its parent. */
export function forks(rows: readonly TreeRow[], nodes: readonly RefineNode[]): Fork[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const oldest = new Map<string, RefineNode>();
  for (const n of nodes) if (!oldest.has(n.branch)) oldest.set(n.branch, n);
  const bottom = new Map<string, number>();
  rows.forEach((r, i) => {
    const b = branchOfRow(r);
    if (b !== null) bottom.set(b, i);
  });
  const out: Fork[] = [];
  for (const [branch, from] of bottom) {
    const first = oldest.get(branch);
    const parent = first?.parent ?? null;
    if (parent === null) continue;
    const to = anchorRow(rows, byId, parent);
    if (to === null || to <= from) continue;
    const toBranch = byId.get(parent)?.branch ?? null;
    out.push({ branch, from, to, toBranch: toBranch !== null && rows.some((r) => branchOfRow(r) === toBranch) ? toBranch : null });
  }
  return out;
}

export interface Lanes {
  lane: Map<string, number>;
  count: number;
}

/** Git-graph lane packing over the VISIBLE rows: a branch holds a lane from
 * its first row down to where its fork lands, and a lane is reused once
 * free - so 28 branches no longer mean 28 columns. */
export function packLanes(rows: readonly TreeRow[], nodes: readonly RefineNode[]): Lanes {
  const first = new Map<string, number>();
  const last = new Map<string, number>();
  rows.forEach((r, i) => {
    const b = branchOfRow(r);
    if (b === null) return;
    if (!first.has(b)) first.set(b, i);
    last.set(b, i);
  });
  for (const f of forks(rows, nodes)) {
    last.set(f.branch, Math.max(last.get(f.branch) ?? 0, f.to));
  }
  const order = [...first.entries()].sort((a, b) => a[1] - b[1]).map(([b]) => b);
  const busyThrough: number[] = [];
  const lane = new Map<string, number>();
  for (const b of order) {
    const start = first.get(b) ?? 0;
    const end = last.get(b) ?? start;
    let l = busyThrough.findIndex((through) => through < start);
    if (l === -1) {
      l = busyThrough.length;
      busyThrough.push(end);
    } else {
      busyThrough[l] = end;
    }
    lane.set(b, l);
  }
  return { lane, count: busyThrough.length };
}
