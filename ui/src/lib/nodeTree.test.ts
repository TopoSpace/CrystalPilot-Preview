import { describe, expect, it } from "vitest";
import {
  anchorRow,
  bestNodeId,
  deliveriesByNode,
  forks,
  isFolded,
  metricsView,
  packLanes,
  treeRows,
  type FoldState,
} from "./nodeTree";
import type { RefineNode } from "./wbTypes";

function node(
  id: string,
  parent: string | null,
  branch: string,
  over: Partial<RefineNode> = {},
): RefineNode {
  return {
    id,
    parent,
    branch,
    tool: "run_shelxl",
    note: "",
    n_atoms: 10,
    r1: null,
    wr2: null,
    goof: null,
    diff_map_max: null,
    diff_map_min: null,
    n_params: null,
    metrics_current: false,
    n_restraints: 0,
    ...over,
  };
}

/** main: n0 -> n1 -> n2; hypothesis forks at n1: n3 -> n4; two diag
 * probes off n2: n5, n6 (separate branches); n7 continues main. */
const NODES: RefineNode[] = [
  node("n0000", null, "main", { r1: 0.2, metrics_current: true, tool: "solve" }),
  node("n0001", "n0000", "main", { r1: 0.1, metrics_current: true }),
  node("n0002", "n0001", "main", { r1: 0.1, tool: "add_atoms" }),
  node("n0003", "n0001", "hypothesis/a", { r1: 0.1, tool: "edit_atoms" }),
  node("n0004", "n0003", "hypothesis/a", { r1: 0.08, metrics_current: true }),
  node("n0005", "n0002", "diag/probe_site/n0002/C@0,0,0", { r1: 0.07, metrics_current: true }),
  node("n0006", "n0002", "diag/probe_site/n0002/reference", { r1: 0.1, metrics_current: true }),
  node("n0007", "n0002", "main", { r1: 0.09, metrics_current: true }),
];

const OPEN: FoldState = { branches: new Map(), diag: false };
const DEFAULT: FoldState = { branches: new Map(), diag: true };

describe("treeRows", () => {
  it("puts a header above each branch's newest node and folds diag/* into one row by default", () => {
    const rows = treeRows(NODES, DEFAULT);
    expect(
      rows.map((r) =>
        r.kind === "node" ? r.node.id : r.kind === "branch" ? `[${r.branch}]` : "[diag]",
      ),
    ).toEqual([
      "[main]", "n0007", "[diag]", "n0004".replace("n0004", "[hypothesis/a]"), "n0004", "n0003",
      "n0002", "n0001", "n0000",
    ]);
    const diag = rows.find((r) => r.kind === "diag");
    expect(diag).toEqual({ kind: "diag", branches: 2, nodes: 2, folded: true });
    const main = rows[0];
    expect(main.kind === "branch" && main.count === 4 && main.head.id === "n0007").toBe(true);
  });

  it("a folded branch is only its header; diag branches stay folded even when the family is open", () => {
    const folds: FoldState = { branches: new Map([["hypothesis/a", true]]), diag: false };
    const rows = treeRows(NODES, folds);
    expect(rows.filter((r) => r.kind === "node").map((r) => (r as { node: RefineNode }).node.id)).toEqual([
      "n0007", "n0002", "n0001", "n0000",
    ]);
    // the family row still heads the diag branches when they are shown
    const diagRow = rows.findIndex((r) => r.kind === "diag");
    expect(rows[diagRow]).toMatchObject({ kind: "diag", folded: false });
    expect(rows[diagRow + 1]).toMatchObject({ kind: "branch", branch: "diag/probe_site/n0002/reference" });
    const heads = rows.filter((r) => r.kind === "branch") as { branch: string; folded: boolean }[];
    expect(heads.map((h) => [h.branch, h.folded])).toEqual([
      ["main", false],
      ["diag/probe_site/n0002/reference", true],
      ["diag/probe_site/n0002/C@0,0,0", true],
      ["hypothesis/a", true],
    ]);
    expect(isFolded("diag/x", OPEN)).toBe(true);
    expect(isFolded("diag/x", { branches: new Map([["diag/x", false]]), diag: false })).toBe(false);
  });
});

describe("metrics and marks", () => {
  const byId = new Map(NODES.map((n) => [n.id, n]));

  it("names the refined ancestor a carried R1 comes from", () => {
    expect(metricsView(byId, "n0001")).toMatchObject({ r1: 0.1, current: true, source: null });
    expect(metricsView(byId, "n0002")).toMatchObject({ r1: 0.1, current: false, source: "n0001" });
    // two unrefined steps in a row still resolve to the same ancestor
    expect(metricsView(byId, "n0003")).toMatchObject({ r1: 0.1, current: false, source: "n0001" });
    expect(metricsView(byId, "n0004")).toMatchObject({ r1: 0.08, current: true });
  });

  it("the best node is the lowest current R1 outside diag/*", () => {
    // n0005 (0.07) is a probe candidate: excluded; n0004 (0.08) wins
    expect(bestNodeId(NODES)).toBe("n0004");
    expect(bestNodeId([node("x", null, "main")])).toBeNull();
  });

  it("groups deliveries by node", () => {
    const m = deliveriesByNode([
      { node: "n0007", status: "final", rel: "task_1" },
      { node: "n0004", status: "diagnostic", rel: "task_1/guest" },
      { node: "n0007", status: "provisional", rel: "task_2" },
    ]);
    expect(m.get("n0007")?.map((d) => d.rel)).toEqual(["task_1", "task_2"]);
    expect(m.get("n0004")?.length).toBe(1);
  });
});

describe("lanes and forks", () => {
  it("forks land on the parent's row, or on the folded row standing in for it", () => {
    const rows = treeRows(NODES, OPEN);
    const byId = new Map(NODES.map((n) => [n.id, n]));
    const idx = (id: string) => anchorRow(rows, byId, id)!;
    const f = forks(rows, NODES);
    const hyp = f.find((x) => x.branch === "hypothesis/a")!;
    expect(hyp.to).toBe(idx("n0001"));
    expect(hyp.toBranch).toBe("main");
    // a diag branch is folded (header only): its fork leaves the header row
    const diag = f.find((x) => x.branch.startsWith("diag/probe_site/n0002/C"))!;
    expect(rows[diag.from].kind).toBe("branch");
    expect(diag.to).toBe(idx("n0002"));
    // with the family folded, n0005 resolves to the diag row and main has no fork
    const folded = treeRows(NODES, DEFAULT);
    expect(rows.length).toBeGreaterThan(folded.length);
    expect(folded[anchorRow(folded, byId, "n0005")!].kind).toBe("diag");
    expect(forks(folded, NODES).some((x) => x.branch === "main")).toBe(false);
  });

  it("packs branches into few lanes and reuses a lane once its fork has landed", () => {
    const rows = treeRows(NODES, OPEN);
    const { lane, count } = packLanes(rows, NODES);
    expect(lane.get("main")).toBe(0);
    // every side branch here is still "open" (its fork has not landed)
    // while the others start, so nothing can share: four lanes
    expect(count).toBe(4);
    expect(new Set(lane.values()).size).toBe(count);
    const folded = treeRows(NODES, DEFAULT);
    expect(packLanes(folded, NODES).count).toBe(2);

    // sequential side branches share a lane: B (newer, forks from n2)
    // has landed by the time A (older, forks from n0) starts
    const seq: RefineNode[] = [
      node("n0", null, "main", { r1: 0.2, metrics_current: true }),
      node("n1", "n0", "main"),
      node("a1", "n0", "A"),
      node("n2", "n1", "main"),
      node("b1", "n2", "B"),
      node("n3", "n2", "main"),
    ];
    const seqRows = treeRows(seq, OPEN);
    const packed = packLanes(seqRows, seq);
    expect(packed.count).toBe(2);
    expect(packed.lane.get("A")).toBe(1);
    expect(packed.lane.get("B")).toBe(1);
  });
});
