/** Anchor jumps (round-3 R6): clicking `[anchor node=n0116 atoms=O1(-x,y,-z)]`
 * views that node and selects that atom - immediately when its scene is on
 * screen, otherwise once the scene of that node arrives, and never in the
 * scene of a different node. */
import { describe, expect, it } from "vitest";
import type { SceneResponse } from "../lib/wbTypes";
import { atomIndexForLabel, crystalReducer, initialCrystalState } from "./crystalReducer";

function scene(atoms: { label: string; sym?: boolean; symop?: string }[]): SceneResponse {
  return {
    mode: "asu",
    atoms: atoms.map((a) => ({
      label: a.label,
      elem: a.label.replace(/\d.*$/, ""),
      xyz: [0, 0, 0],
      occ: 1,
      u_eq: 0.03,
      sym: a.sym ?? false,
      ...(a.symop ? { symop: a.symop } : {}),
    })),
    bonds: [],
  } as unknown as SceneResponse;
}

const S = scene([
  { label: "O1" },
  { label: "N2" },
  { label: "O1", sym: true, symop: "-x,y,-z" },
]);

describe("atomIndexForLabel", () => {
  it("prefers the asymmetric-unit atom for a bare label", () => {
    expect(atomIndexForLabel(S, "O1")).toBe(0);
    expect(atomIndexForLabel(S, "o1")).toBe(0);
  });
  it("finds the symmetry copy by operator and falls back to the ASU atom", () => {
    expect(atomIndexForLabel(S, "O1(-x,y,-z)")).toBe(2);
    expect(atomIndexForLabel(S, "O1( -x, y, -z )")).toBe(2);
    expect(atomIndexForLabel(S, "O1(x+1,y,z)")).toBe(0);
  });
  it("is -1 for an atom this scene does not draw", () => {
    expect(atomIndexForLabel(S, "C9")).toBe(-1);
  });
});

describe("select_label", () => {
  const base = { ...initialCrystalState(), activeNode: "n0116", viewNode: "n0116" };

  it("selects at once when the viewed node's scene is on screen", () => {
    const st = crystalReducer(
      { ...base, scene: S, sceneNode: "n0116", sceneStatus: "ok" },
      { type: "select_label", node: "n0116", label: "N2" },
    );
    expect(st.selection?.index).toBe(1);
    expect(st.pendingSelect).toBeNull();
  });

  it("waits for the scene of another node and resolves on scene_ok", () => {
    let st = crystalReducer(
      { ...base, scene: S, sceneNode: "n0116", sceneStatus: "ok" },
      { type: "view_node", node: "n0079" },
    );
    st = crystalReducer(st, { type: "select_label", node: "n0079", label: "O1(-x,y,-z)" });
    // the old node's scene is still on screen: nothing selected in it
    expect(st.selection).toBeNull();
    expect(st.pendingSelect).toEqual({ node: "n0079", label: "O1(-x,y,-z)" });
    st = crystalReducer(st, { type: "scene_ok", scene: S });
    expect(st.selection?.index).toBe(2);
    expect(st.pendingSelect).toBeNull();
  });

  it("drops a pending selection when the scene that arrives is for a different node", () => {
    let st = crystalReducer(base, { type: "select_label", node: "n0079", label: "O1" });
    // the user meanwhile viewed another node; its scene must not inherit the pick
    st = crystalReducer(st, { type: "view_node", node: "n0080" });
    st = crystalReducer(st, { type: "scene_ok", scene: S });
    expect(st.selection).toBeNull();
    expect(st.pendingSelect).toBeNull();
  });

  it("an unknown label selects nothing and leaves no pending pick", () => {
    const st = crystalReducer(
      { ...base, scene: S, sceneNode: "n0116", sceneStatus: "ok" },
      { type: "select_label", node: "n0116", label: "C9" },
    );
    expect(st.selection).toBeNull();
    expect(st.pendingSelect).toBeNull();
  });
});
