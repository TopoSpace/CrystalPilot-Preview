import { describe, expect, it } from "vitest";
import type { RefineNode, SceneAtom, SceneResponse } from "../lib/wbTypes";
import { crystalReducer as reduce, initialCrystalState, sceneMatchesRequest } from "./crystalReducer";

const nodes = [
  { id: "n0001", parent: null },
  { id: "n0002", parent: "n0001" },
  { id: "n0003", parent: "n0002" },
] as RefineNode[];
const atom: SceneAtom = { label: "O1", elem: "O", sym: false, xyz: [1, 2, 3], occ: 1, u_eq: 0.03 };
const scene = (node: string, atoms = [atom]): SceneResponse => ({ node, mode: "asu", atoms } as SceneResponse);
const base = () => ({ ...initialCrystalState(), nodes, activeNode: "n0003", viewNode: "n0003", scene: scene("n0003"), sceneNode: "n0003", sceneStatus: "ok" as const });

describe("readonly pinned comparison", () => {
  it("pins the explicit pair without changing the scientific node", () => {
    const state = reduce(base(), { type: "begin_comparison", baseline: "n0001" });
    expect(state.comparison).toMatchObject({ node: "n0003", baseline: "n0001" });
    expect(state.follow).toBe(false);
    expect(state.activeNode).toBe("n0003");
    expect(state.overlays.diff).toBe(false);
    const next = reduce(state, { type: "nodes_ok", nodes: [...nodes, { id: "n0004", parent: "n0003" } as RefineNode], activeNode: "n0004", activeBranch: "main", branches: { main: "n0004" } });
    expect(next.viewNode).toBe("n0003");
    expect(next.comparison?.node).toBe("n0003");
    expect(reduce(next, { type: "end_comparison" }).viewNode).toBe("n0004");
  });

  it("defaults to the parent and rejects missing or identical nodes", () => {
    expect(reduce(base(), { type: "begin_comparison", baseline: null }).comparison?.baseline).toBe("n0002");
    expect(reduce(base(), { type: "begin_comparison", baseline: "n0003" })).toEqual(base());
    expect(reduce(base(), { type: "begin_comparison", baseline: "n0099" })).toEqual(base());
    expect(reduce({ ...base(), viewNode: "n0001" }, { type: "begin_comparison", baseline: null }).comparison).toBeNull();
  });

  it("does not infer cross-node atom identity, even when a label is reused", () => {
    let state = reduce({ ...base(), selection: { atom, index: 0 }, grown: [{ i: 12, op: "x+1,y,z" }] }, { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    expect(state.selection).toBeNull();
    expect(state.grown).toEqual([]);
    state = reduce(state, { type: "scene_ok", scene: scene("n0001") });
    expect(state.selection).toBeNull();
    state = reduce(state, { type: "comparison_side", node: "n0003" });
    expect(state.grown).toEqual([{ i: 12, op: "x+1,y,z" }]);
    state = reduce(state, { type: "scene_ok", scene: scene("n0003") });
    expect(state.selection?.atom.label).toBe("O1");
    expect(state.activeNode).toBe("n0003");
  });

  it("restores independent historical viewing intent and exits on navigation", () => {
    const state = reduce({ ...base(), viewNode: "n0002", follow: false }, { type: "begin_comparison", baseline: "n0001" });
    const before = reduce(state, { type: "comparison_side", node: "n0001" });
    const exited = reduce(before, { type: "end_comparison" });
    expect(exited.viewNode).toBe("n0002");
    expect(exited.follow).toBe(false);
    expect(exited.comparison).toBeNull();
    expect(reduce(before, { type: "follow_latest" }).comparison).toBeNull();
    expect(reduce(before, { type: "view_node", node: "n0001" }).comparison).toBeNull();
    expect(reduce(before, { type: "select_label", node: "n0002", label: "O1" }).comparison).toBeNull();
  });

  it("restores the subject selection through the return-scene load after exiting the baseline", () => {
    const image = { ...atom, sym: true, symop: "x+1,y,z", part: 2 };
    let state = reduce({ ...base(), scene: scene("n0003", [image]), selection: { atom: image, index: 0 } }, { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0001") });
    state = reduce(state, { type: "end_comparison" });
    expect(state.selection?.atom.symop).toBe("x+1,y,z");
    state = reduce(state, { type: "scene_ok", scene: scene("n0003", [atom, image]) });
    expect(state.comparison).toBeNull();
    expect(state.selection?.index).toBe(1);
    expect(state.selection?.atom.symop).toBe("x+1,y,z");
  });

  it("never substitutes ASU for a missing return-scene symmetry selection", () => {
    const image = { ...atom, sym: true, symop: "x+1,y,z" };
    let state = reduce({ ...base(), selection: { atom: image, index: 0 } }, { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0001") });
    state = reduce(state, { type: "end_comparison" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0003", [atom]) });
    expect(state.selection).toBeNull();
  });

  it("keeps the original subject when replacing a baseline from the before side", () => {
    let state = reduce(base(), { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    state = reduce(state, { type: "begin_comparison", baseline: "n0002" });
    expect(state.comparison).toMatchObject({ node: "n0003", baseline: "n0002" });
    expect(state.viewNode).toBe("n0003");
  });

  it("leaves comparison when a pinned node is no longer listed", () => {
    const state = reduce(base(), { type: "begin_comparison", baseline: "n0001" });
    const next = reduce(state, { type: "nodes_ok", nodes: nodes.slice(1), activeNode: "n0003", activeBranch: "main", branches: { main: "n0003" } });
    expect(next.comparison).toBeNull();
    expect(next.viewNode).toBe("n0003");
  });

  it("does not revive old hand-grown instances after a shared slice change", () => {
    let state = reduce({ ...base(), grown: [{ i: 12, op: "x+1,y,z" }] }, { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    state = reduce(state, { type: "set_mode", mode: "cell" });
    state = reduce(state, { type: "comparison_side", node: "n0003" });
    expect(state.grown).toEqual([]);
  });

  it("does not promote a requested camera key before that scene finishes loading", () => {
    let state = reduce(base(), { type: "scene_ok", scene: scene("n0003"), key: undefined });
    state = reduce(state, { type: "scene_loading", key: "asu" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0003"), key: "asu" });
    expect(sceneMatchesRequest(state, "asu")).toBe(true);
    // The first render after a range command precedes the fetch effect's loading action.
    state = reduce(state, { type: "set_super_n", n: 2 });
    expect(state.sceneStatus).toBe("ok");
    expect(sceneMatchesRequest(state, "super")).toBe(false);
    state = reduce(state, { type: "scene_loading", key: "super" });
    state = reduce(state, { type: "scene_ok", key: "super", scene: { ...scene("n0003"), mode: "supercell" } });
    expect(sceneMatchesRequest(state, "super")).toBe(true);
  });

  it("drops a queued comparison selection when a different node is explicitly viewed", () => {
    let state = reduce({ ...base(), selection: { atom, index: 0 } }, { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "comparison_side", node: "n0001" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0001") });
    state = reduce(state, { type: "end_comparison" });
    state = reduce(state, { type: "view_node", node: "n0002" });
    state = reduce(state, { type: "scene_ok", scene: scene("n0002") });
    expect(state.selection).toBeNull();
    expect(state.selectionRestore).toBeNull();
  });

  it("rejects late same-node range responses as well as another node's scene", () => {
    let state = reduce(base(), { type: "begin_comparison", baseline: "n0001" });
    state = reduce(state, { type: "scene_loading", key: "range-B" });
    expect(reduce(state, { type: "scene_ok", key: "range-A", scene: scene("n0003") })).toBe(state);
    expect(reduce(state, { type: "scene_error", key: "range-A", error: "late" })).toBe(state);
    expect(reduce(state, { type: "scene_ok", key: "range-B", scene: scene("n0001") })).toBe(state);
    expect(reduce(state, { type: "scene_ok", key: "range-B", scene: scene("n0003") }).sceneStatus).toBe("ok");
  });
});
