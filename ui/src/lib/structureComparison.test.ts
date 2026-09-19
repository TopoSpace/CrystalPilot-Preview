import { describe, expect, it } from "vitest";
import type { NodeComparisonResponse, RefineNode, SceneAtom, SceneResponse } from "./wbTypes";
import { ComparisonCameras, comparableMetric, matchesComparison, comparisonNumber, comparisonSelection, signedDifference } from "./structureComparison";

const atom = (extra: Partial<SceneAtom> = {}): SceneAtom => ({ label: "O1", elem: "O", xyz: [1, 2, 3], occ: 1, u_eq: 0.02, sym: false, ...extra });
const scene = (atoms: SceneAtom[]) => ({ node: "n0002", atoms } as SceneResponse);

describe("comparison instance identity", () => {
  it("resolves an exact label, PART and absolute operator, not the old index", () => {
    const selected = { atom: atom({ sym: true, symop: "-x, y+1, z", part: 2 }), index: 99 };
    const result = comparisonSelection(scene([atom(), atom({ part: 1, sym: true, symop: "-x,y+1,z" }), atom({ part: 2, sym: true, symop: "-x,y+1,z" })]), selected);
    expect(result?.index).toBe(2);
  });
  it("never replaces an absent symmetry image with the ASU", () => {
    expect(comparisonSelection(scene([atom()]), { atom: atom({ sym: true, symop: "x+1,y,z" }), index: 0 })).toBeNull();
  });
  it("refuses incomplete or duplicate identities and removed ghosts", () => {
    expect(comparisonSelection(scene([atom({ sym: true })]), { atom: atom({ sym: true }), index: 0 })).toBeNull();
    expect(comparisonSelection(scene([atom(), atom()]), { atom: atom(), index: 0 })).toBeNull();
    expect(comparisonSelection(scene([atom({ flag: "removed" })]), { atom: atom(), index: 0 })).toBeNull();
  });
  it("normalizes an omitted PART to zero, without inventing a symmetry transform", () => {
    expect(comparisonSelection(scene([atom({ part: 0 })]), { atom: atom(), index: 0 })?.index).toBe(0);
    expect(comparisonSelection(scene([atom({ sym: true, symop: "x+0,y,z" })]), { atom: atom(), index: 0 })).toBeNull();
  });
});

describe("neutral comparison numbers", () => {
  it("retains numeric differences without a scientific verdict", () => {
    expect(signedDifference(0.0381, 0.0656, 4)).toBe("−0.0275");
    expect(signedDifference(24, 13, 0)).toBe("+11");
    expect(signedDifference(1.00001, 1, 2)).toBe("0.00");
  });
  it.each([null, undefined, NaN, Infinity])("leaves missing %s unknown", (value) => {
    expect(comparisonNumber(value, 4)).toBe("—");
    expect(signedDifference(value, 1, 4)).toBe("—");
  });
});

describe("synthetic comparison provenance decisions", () => {
  const node = { id: "n0004", revision: 4, metrics_current: true, r1: 0.04, wr2: 0.12, goof: 1.1 } as RefineNode;
  const baseline = { id: "n0002", revision: 2, metrics_current: true, r1: 0.05, wr2: 0.14, goof: 1.2 } as RefineNode;
  const response = (): NodeComparisonResponse => ({ schema: 1, node: node.id, baseline: baseline.id, project_revision: 7,
    sources: Object.fromEntries(([['node', node], ['baseline', baseline]] as const).map(([side, item]) => [side, {
      node: item.id, model_revision: item.revision, metrics_current: true, data_binding: 'bound', data_revision: 'fixture-data',
      metrics_source: { node: item.id, model_revision: item.revision, data_revision: 'fixture-data', engine: 'fixture' },
      frame: { revision: null, cell: null, space_group_operations: null }, evidence: { reflection_recompute: false, reason: null },
    }])), metrics: { r1: { status: 'comparable', reasons: [] }, wr2: { status: 'different', reasons: ['weighting'] }, goof: { status: 'unknown', reasons: ['definition'] } },
    frame: { status: 'compatible', reasons: [] }, differences: [], unknown_fields: [],
  } as unknown as NodeComparisonResponse);
  it("consumes each metric decision, rather than rejecting all R factors after a weight change", () => {
    expect(comparableMetric(response(), 'r1', node, baseline)).toBe(true);
    expect(comparableMetric(response(), 'wr2', node, baseline)).toBe(false);
    expect(comparableMetric(response(), 'goof', node, baseline)).toBe(false);
  });
  it("rejects wrong pairs, stale revisions and inherited measurement sources", () => {
    const data = response();
    expect(matchesComparison(data, { ...node, revision: 5 }, baseline)).toBe(false);
    expect(matchesComparison(data, baseline, node)).toBe(false);
    expect(comparableMetric(data, 'r1', { ...node, metrics_current: false }, baseline)).toBe(false);
    data.sources.node.metrics_source!.node = baseline.id;
    expect(comparableMetric(data, 'r1', node, baseline)).toBe(false);
  });
  it("does not reward missing values or unknown data binding even with a contradictory verdict", () => {
    const data = response();
    expect(comparableMetric(data, 'r1', { ...node, r1: null }, baseline)).toBe(false);
    data.sources.node.data_binding = 'legacy_unknown';
    expect(comparableMetric(data, 'r1', node, baseline)).toBe(false);
  });
  it("fails closed for a partial or missing contract", () => {
    const data = response();
    delete (data as Partial<NodeComparisonResponse>).metrics;
    expect(matchesComparison(data, node, baseline)).toBe(false);
    expect(comparableMetric(null, 'r1', node, baseline)).toBe(false);
  });
});

describe("comparison camera cache", () => {
  const view = [1, 2, 3, 4, 0, 0, 0, 1];
  it("keeps per-node views independent and returns defensive copies", () => {
    const cameras = new ComparisonCameras();
    cameras.set("n0001", view);
    cameras.set("n0002", [9, ...view.slice(1)]);
    const copy = cameras.get("n0001")!;
    copy[0] = 100;
    expect(cameras.get("n0001")).toEqual(view);
    expect(cameras.get("n0002")?.[0]).toBe(9);
  });
  it("bounds retained cameras and refuses invalid snapshots", () => {
    const cameras = new ComparisonCameras();
    for (let i = 0; i < 9; i++) cameras.set(String(i), view);
    expect(cameras.get("0")).toBeUndefined();
    cameras.set("8", [NaN, ...view.slice(1)]);
    expect(cameras.get("8")).toEqual(view);
  });
});
