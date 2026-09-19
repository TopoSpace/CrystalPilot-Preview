import { describe, expect, it } from "vitest";
import { crystalReducer, initialCrystalState, type CrystalState } from "../state/crystalReducer";
import type {
  InteractionRow,
  SceneAtom,
  SceneResponse,
  UniqueInteractionRow,
} from "./wbTypes";
import {
  exactSelectionInScene,
  findRenderedInteraction,
  interactionIdentity,
} from "./analysisInspector";

function atom(label: string, sym = false, symop?: string): SceneAtom {
  return { label, elem: label[0], xyz: [0, 0, 0], occ: 1, u_eq: 0.02, sym, symop };
}

const canonical: UniqueInteractionRow = {
  kind: "hbond",
  dist: 2.8123,
  passes: true,
  op: "-x, y+1/2, -z",
  d: "N1",
  h: "H1",
  a: "O2",
};

function display(extra: Partial<InteractionRow> = {}): InteractionRow {
  return {
    ...canonical,
    boundary: false,
    sym: "-x,y+1/2,-z",
    sym_i: "x,y,z",
    p: [0, 0, 0],
    q: [1, 1, 1],
    ai: 0,
    bi: 1,
    ...extra,
  } as InteractionRow;
}

function scene(rows?: InteractionRow[]): SceneResponse {
  return {
    mode: "cell",
    atoms: [atom("N1"), atom("O2", true, "-x,y+1/2,-z")],
    bonds: [],
    polyhedra: [],
    node: "n1",
    space_group: "P 1",
    cell: { a: 10, b: 10, c: 10, alpha: 90, beta: 90, gamma: 90, volume: 1000 },
    meta: { n_atoms: 2, n_bonds: 0, n_ghosts: 0, n_polyhedra: 0, truncated: false },
    interactions: rows
      ? ({ rows } as SceneResponse["interactions"])
      : undefined,
  } as SceneResponse;
}

describe("analysis interaction matching", () => {
  it("matches the canonical identity while preserving the rendered symmetry instance", () => {
    const match = findRenderedInteraction(scene([display()]), canonical);
    expect(match?.atomIndex).toBe(1);
    expect(match?.row.bi).toBe(1);
    expect(interactionIdentity(match!.row)).toBe(interactionIdentity(canonical));
  });

  it("prefers an in-range segment over a boundary copy", () => {
    const boundary = display({ boundary: true, ai: 0, bi: null, sym_i: "x+1,y,z" });
    const complete = display({ ai: 0, bi: 1 });
    expect(findRenderedInteraction(scene([boundary, complete]), canonical)?.row.boundary).toBe(false);
  });

  it("does not select a similarly labelled row with another operator", () => {
    const wrong = display({ op: "x,y,z", sym: "x,y,z" });
    expect(findRenderedInteraction(scene([wrong]), canonical)).toBeNull();
  });

  it("reports no match before the display layer exists", () => {
    expect(findRenderedInteraction(scene(), canonical)).toBeNull();
  });

  it("does not treat geometry or a display ordinal as scientific identity", () => {
    expect(interactionIdentity(display({ dist: 2.8124, ai: 900 }))).toBe(interactionIdentity(canonical));
    expect(interactionIdentity(display({ h: "H2" }))).not.toBe(interactionIdentity(canonical));
  });

  it("preserves the absolute instance when multiple translated rows exist", () => {
    const other = display({ sym_i: "x+1,y,z", sym: "-x+1,y+1/2,-z" });
    expect(findRenderedInteraction(scene([other]), canonical, display())).toBeNull();
    expect(findRenderedInteraction(scene([other, display()]), canonical, display())?.row.sym_i).toBe("x,y,z");
  });

  it("does not invent an atom for a ring-centroid segment", () => {
    const ring = display({ kind: "pipi", ai: null, bi: null, ring_a: "C1-C2-C3", ring_b: "C4-C5-C6" });
    expect(findRenderedInteraction(scene([ring]), ring)?.atomIndex).toBeNull();
  });

  it("does not highlight removed ghosts or invalid display indices", () => {
    const s = scene([display({ ai: 88 })]);
    s.atoms[1].flag = "removed";
    expect(findRenderedInteraction(s, canonical)?.atomIndex).toBeNull();
  });
});

describe("exactSelectionInScene", () => {
  it("keeps a symmetry copy exact across a scene refresh", () => {
    const refreshed = scene([]);
    const found = exactSelectionInScene(refreshed, { atom: atom("O2", true, " -x, y+1/2, -z "), index: 9 });
    expect(found?.index).toBe(1);
    expect(found?.atom.sym).toBe(true);
  });

  it("never falls back to the ASU atom when the selected operation is absent", () => {
    const refreshed = scene([]);
    const found = exactSelectionInScene(refreshed, { atom: atom("N1", true, "x+1,y,z"), index: 4 });
    expect(found).toBeNull();
  });

  it("does not cross disorder identities or guess a missing symmetry operation", () => {
    expect(exactSelectionInScene(scene(), { atom: { ...atom("N1"), part: 2 }, index: 0 })).toBeNull();
    expect(exactSelectionInScene(scene(), { atom: atom("O2", true), index: 1 })).toBeNull();
  });
});

describe("inspector reducer contract", () => {
  function base(s = scene([display()])): CrystalState {
    return { ...initialCrystalState(), viewNode: "n1", activeNode: "n1", sceneNode: "n1", scene: s, sceneStatus: "ok" };
  }
  const inspect = { type: "inspect_interaction", node: "n1", row: canonical } as const;

  it("selects and centers the real symmetry endpoint and enables its layer", () => {
    const next = crystalReducer(base(), inspect);
    expect(next.selection?.index).toBe(1);
    expect(next.selection?.atom.symop).toBe("-x,y+1/2,-z");
    expect(next.focusRequest).toBe(1);
    expect(next.overlays.hbonds).toBe(true);
    expect(next.inspection?.node).toBe("n1");
  });

  it("waits for the requested layer instead of guessing the ASU", () => {
    let next = crystalReducer(base(scene()), inspect);
    expect(next.selection).toBeNull();
    next = crystalReducer(next, { type: "scene_ok", scene: scene([display()]) });
    expect(next.selection?.index).toBe(1);
    expect(next.focusRequest).toBe(1);
  });

  it("rejects an analysis row from another node without enabling a layer", () => {
    const st = base();
    expect(crystalReducer(st, { ...inspect, node: "n0" })).toBe(st);
  });

  it("does not bind an in-flight new node's row to the previous scene", () => {
    const next = crystalReducer({ ...base(), sceneNode: "n0" }, inspect);
    expect(next.selection).toBeNull();
    expect(next.focusRequest).toBe(0);
  });

  it("re-resolves display indices but never substitutes another translation", () => {
    const st = crystalReducer(base(), inspect);
    const moved = scene([display({ ai: 1, bi: 0 })]);
    moved.atoms.reverse();
    expect(crystalReducer(st, { type: "scene_ok", scene: moved }).selection?.index).toBe(0);
    const absent = scene([display({ sym_i: "x+1,y,z", sym: "-x+1,y+1/2,-z" })]);
    const next = crystalReducer(st, { type: "scene_ok", scene: absent });
    expect(next.selection).toBeNull();
    expect(next.inspection).toEqual(st.inspection);
  });

  it("ignores a late scene response for a different node", () => {
    const st = crystalReducer(base(), inspect);
    expect(crystalReducer(st, { type: "scene_ok", scene: { ...scene(), node: "n0" } })).toBe(st);
  });

  it("clears inspection when the active follow node changes", () => {
    const st = crystalReducer(base(), inspect);
    const next = crystalReducer(st, { type: "nodes_ok", nodes: [], activeNode: "n2", activeBranch: "main", branches: {} });
    expect(next.selection).toBeNull();
    expect(next.inspection).toBeNull();
  });

  it("locates coordination only in the scene with matching node and exact atom identity", () => {
    const st = base();
    const selection = { atom: st.scene!.atoms[1], index: 99 };
    expect(crystalReducer(st, { type: "locate", node: "n0", selection })).toBe(st);
    const next = crystalReducer(st, { type: "locate", node: "n1", selection });
    expect(next.selection?.index).toBe(1);
    expect(next.focusRequest).toBe(1);
  });

  it("retains canonical numbers when the display range changes", () => {
    const st = crystalReducer(base(), inspect);
    const next = crystalReducer(st, { type: "set_mode", mode: "super" });
    expect(next.inspection?.row).toBe(canonical);
    expect(next.inspection?.row.dist).toBe(2.8123);
  });
});
