/** Reducer semantics for the density-map kind switch (viewer P1-5). */
import { describe, expect, it } from "vitest";
import { crystalReducer, initialCrystalState } from "./crystalReducer";

describe("set_map_kind", () => {
  it("switches kind, resets iso to the per-kind default and drops the buffer", () => {
    let s = initialCrystalState();
    s = crystalReducer(s, {
      type: "map_ok",
      node: "n0001",
      buffer: new ArrayBuffer(8),
    });
    s = crystalReducer(s, { type: "set_iso", iso: 0.8 });

    const two = crystalReducer(s, { type: "set_map_kind", kind: "2fofc" });
    expect(two.mapKind).toBe("2fofc");
    expect(two.iso).toBe(1.5);
    expect(two.mapBuffer).toBeNull();
    expect(two.mapNode).toBeNull();
    expect(two.mapStatus).toBe("idle");

    const back = crystalReducer(two, { type: "set_map_kind", kind: "fofc" });
    expect(back.mapKind).toBe("fofc");
    expect(back.iso).toBe(0.35);
  });

  it("is a no-op when the kind is unchanged (keeps buffer and iso)", () => {
    let s = initialCrystalState();
    s = crystalReducer(s, {
      type: "map_ok",
      node: "n0001",
      buffer: new ArrayBuffer(8),
    });
    s = crystalReducer(s, { type: "set_iso", iso: 0.6 });
    const same = crystalReducer(s, { type: "set_map_kind", kind: "fofc" });
    expect(same).toBe(s);
  });
});

/** Draw style replaces the lone 椭球 toggle: Olex2's representations are
 * mutually exclusive, and there was previously no way to ask for a
 * wireframe on a supercell or spacefill on a pore. */
describe("draw style", () => {
  it("defaults to ORTEP - a reviewer looks at ADPs first", () => {
    expect(initialCrystalState().drawStyle).toBe("ellipsoid");
  });

  it("switches and is a no-op on the current style", () => {
    const wire = crystalReducer(initialCrystalState(), {
      type: "set_draw_style",
      style: "wire",
    });
    expect(wire.drawStyle).toBe("wire");
    expect(crystalReducer(wire, { type: "set_draw_style", style: "wire" })).toBe(
      wire,
    );
  });

  it("is independent of extent: switching mode keeps the style", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_draw_style",
      style: "space",
    });
    s = crystalReducer(s, { type: "set_mode", mode: "super" });
    expect(s.drawStyle).toBe("space");
  });
});

/** 生长 is an ACTION applied to whatever slice is on screen, pressed as
 * many times as you like - not a slot in the extent selector. Getting this
 * wrong was the whole of the first attempt: growth was modelled as a mode,
 * so it could not be combined with a packed cell and stopped after one
 * click. */
describe("grow level", () => {
  it("starts ungrown and is independent of the slice", () => {
    const s = initialCrystalState();
    expect(s.growLevel).toBe(0);
    expect(s.mode).toBe("asu");
  });

  it("accumulates one shell per press, from any slice", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_mode",
      mode: "cell",
    });
    for (const level of [1, 2, 3, 4] as const) {
      s = crystalReducer(s, { type: "set_grow_level", level });
      expect(s.growLevel).toBe(level);
      // pressing 生长 must not throw you back to some other slice
      expect(s.mode).toBe("cell");
    }
  });

  it("keeps the selection and hand-grown fragments across a press", () => {
    // otherwise the button is unusable: you click an atom, press 生长 to
    // see its neighbours, and the atom you were looking at is deselected
    let s = crystalReducer(initialCrystalState(), {
      type: "grow_stub",
      i: 3,
      op: "-x,-y,-z",
    });
    s = crystalReducer(s, {
      type: "select",
      selection: { atom: { label: "C1" } as never, index: 1 },
    });
    const grown = crystalReducer(s, { type: "set_grow_level", level: 1 });
    expect(grown.grown).toHaveLength(1);
    expect(grown.selection?.index).toBe(1);
  });

  it("fuses back to ungrown", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_grow_level",
      level: 3,
    });
    s = crystalReducer(s, { type: "set_grow_level", level: 0 });
    expect(s.growLevel).toBe(0);
  });

  it("resets when the slice changes - a new pack starts ungrown", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_grow_level",
      level: 2,
    });
    s = crystalReducer(s, { type: "set_mode", mode: "super" });
    expect(s.growLevel).toBe(0);
  });

  it("is a no-op at the current level", () => {
    const s = crystalReducer(initialCrystalState(), {
      type: "set_grow_level",
      level: 2,
    });
    expect(crystalReducer(s, { type: "set_grow_level", level: 2 })).toBe(s);
  });
});

/** Olex2's element row: on a MOF the useful move is hiding C and H to see
 * the metal-oxygen node. This replaces the lone 氢原子 toggle, which could
 * only ever answer one element. */
describe("element visibility", () => {
  it("starts with everything shown", () => {
    expect(initialCrystalState().hiddenElems).toEqual([]);
  });

  it("toggles an element both ways", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "toggle_elem",
      elem: "C",
    });
    expect(s.hiddenElems).toEqual(["C"]);
    s = crystalReducer(s, { type: "toggle_elem", elem: "C" });
    expect(s.hiddenElems).toEqual([]);
  });

  it("auto-hides H when packing, and shows it again in the ASU", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_mode",
      mode: "cell",
    });
    expect(s.hiddenElems).toContain("H");
    s = crystalReducer(s, { type: "set_mode", mode: "asu" });
    expect(s.hiddenElems).not.toContain("H");
  });

  it("only H is auto-managed: a hand-hidden element survives a repack", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "toggle_elem",
      elem: "C",
    });
    s = crystalReducer(s, { type: "set_mode", mode: "cell" });
    expect(s.hiddenElems).toContain("C");
    expect(s.hiddenElems).toContain("H");
    s = crystalReducer(s, { type: "set_mode", mode: "asu" });
    expect(s.hiddenElems).toEqual(["C"]);
  });

  it("does not double-add H when packing twice", () => {
    let s = crystalReducer(initialCrystalState(), {
      type: "set_mode",
      mode: "cell",
    });
    s = crystalReducer(s, { type: "set_mode", mode: "super" });
    expect(s.hiddenElems.filter((e) => e === "H")).toHaveLength(1);
  });
});

describe("pack slices (Olex2 pack r / pack range / grow -w)", () => {
  it("a radius pick names the slice, clamps the radius and keeps the centre", () => {
    let s = initialCrystalState();
    s = crystalReducer(s, { type: "set_grow_level", level: 2 });
    s = crystalReducer(s, { type: "set_pack_radius", radius: 60, center: "Zn1" });
    expect(s.mode).toBe("radius");
    expect(s.packRadius).toBe(30);
    expect(s.packCenter).toBe("Zn1");
    // a new slice starts ungrown, like pack
    expect(s.growLevel).toBe(0);
    // H stays visible: a radius pack is a local view, not a packed cell
    expect(s.hiddenElems).toEqual([]);
    const same = crystalReducer(s, { type: "set_pack_radius", radius: 30, center: "Zn1" });
    expect(same).toBe(s);
  });

  it("a range pick is a bulky slice: H auto-hides like a packed cell", () => {
    let s = initialCrystalState();
    s = crystalReducer(s, {
      type: "set_pack_range",
      range: { lo: [-0.5, -0.5, -0.5], hi: [1.5, 1.5, 1.5] },
    });
    expect(s.mode).toBe("range");
    expect(s.hiddenElems).toEqual(["H"]);
    expect(s.packRange.hi).toEqual([1.5, 1.5, 1.5]);
  });

  it("grow -w composes with growth and resets with the slice", () => {
    let s = initialCrystalState();
    s = crystalReducer(s, { type: "set_grow_level", level: 1 });
    s = crystalReducer(s, { type: "set_complete", complete: true });
    expect(s.complete).toBe(true);
    expect(s.growLevel).toBe(1);
    expect(crystalReducer(s, { type: "set_complete", complete: true })).toBe(s);
    s = crystalReducer(s, { type: "set_mode", mode: "cell" });
    expect(s.complete).toBe(false);
  });
});

describe("camera viewing depth", () => {
  it("defaults to a full atom span with distance fog disabled", () => {
    expect(initialCrystalState().viewDepth).toEqual({
      fog: false,
      fogStart: 0.55,
      clip: 1,
    });
  });

  it("normalizes unsafe values and is a no-op when normalized settings match", () => {
    const initial = initialCrystalState();
    expect(
      crystalReducer(initial, {
        type: "set_view_depth",
        viewDepth: { fogStart: Number.NaN, clip: Number.POSITIVE_INFINITY },
      }),
    ).toBe(initial);

    const bounded = crystalReducer(initial, {
      type: "set_view_depth",
      viewDepth: { fog: true, fogStart: -2, clip: 4 },
    });
    expect(bounded.viewDepth).toEqual({ fog: true, fogStart: 0.2, clip: 1 });
  });

  it("resets all camera-depth settings without touching the scientific slab", () => {
    let state = crystalReducer(initialCrystalState(), {
      type: "set_slab",
      slab: { axis: 1, center: 0.4, thickness: 0.2 },
    });
    state = crystalReducer(state, {
      type: "set_view_depth",
      viewDepth: { fog: true, fogStart: 0.8, clip: 0.35 },
    });
    const reset = crystalReducer(state, { type: "reset_view_depth" });
    expect(reset.viewDepth).toEqual({ fog: false, fogStart: 0.55, clip: 1 });
    expect(reset.slab).toEqual({ axis: 1, center: 0.4, thickness: 0.2 });
  });
});
