/** The extent/grow menu (round-2 R1.2/R1.3) as data: Olex2 semantics, which
 * items are offered/enabled per state, and what each one dispatches. */
import { describe, expect, it, vi } from "vitest";
import { extentItems, type ExtentActions, type ExtentState } from "./CrystalToolbar";

// vi.fn() is typed as a generic mock; cast each to the action signature so
// the object satisfies ExtentActions while expect() still sees a mock
const fn = <T>(): T => vi.fn() as unknown as T;

function acts(): ExtentActions {
  return {
    setMode: fn(),
    setGrowLevel: fn(),
    setSuperN: fn(),
    setPackRadius: fn(),
    setPackRange: fn(),
    setComplete: fn(),
    setGrowAll: fn(),
    fuse: fn(),
    assemble: fn(),
  };
}

function st(over: Partial<ExtentState> = {}): ExtentState {
  return {
    mode: "asu",
    growLevel: 0,
    superN: 2,
    grown: [],
    complete: false,
    growAll: false,
    packRadius: 8,
    packCenter: null,
    selectionLabel: null,
    ...over,
  };
}

describe("extentItems", () => {
  it("offers the slices (fuse / pack) first and the actions (grow / compaq) after", () => {
    const items = extentItems(st(), acts());
    expect(items.map((i) => i.id)).toEqual([
      "asu", "cell", "super2", "super3", "super4",
      "radius8", "radius16", "range",
      "grow1", "growAll", "complete", "assemble",
    ]);
    expect(items.map((i) => i.hint)).toEqual([
      "fuse", "pack cell", "pack 0 2", "pack 0 3", "pack 0 4",
      "pack 8", "pack 16", "pack -0.5 1.5",
      "grow -s", "grow", "grow -w", "compaq -a",
    ]);
    // two labelled groups: 范围 (a picture) and 动作 (done to the picture)
    expect(items.filter((i) => i.sectionLabel).map((i) => [i.id, i.sectionLabel])).toEqual([
      ["asu", "范围"],
      ["grow1", "动作"],
    ]);
    expect(items.find((i) => i.id === "range")?.label).toBe("分数盒 −0.5…1.5");
    expect(items.find((i) => i.id === "asu")?.active).toBe(true);
    expect(items.some((i) => i.id === "fuse")).toBe(false);
    // the radius pack is centred on the ASU centroid when nothing is selected
    expect(items.find((i) => i.id === "radius8")?.label).toContain("非对称单元质心");
  });

  it("offers Olex2 grow (grow all) as a toggle that says where it stops", () => {
    const item = extentItems(st(), acts()).find((i) => i.id === "growAll")!;
    expect(item.label).toBe("长满");
    expect(item.hint).toBe("grow");
    expect(item.title).toContain("有限分子长完整");
    expect(item.title).toContain("周期");
    expect(item.active).toBeFalsy();
    const on = extentItems(st({ growAll: true }), acts());
    expect(on.find((i) => i.id === "growAll")?.active).toBe(true);
    // grow-all alone counts as grown: 收回 is offered
    expect(on.some((i) => i.id === "fuse")).toBe(true);
  });

  it("marks the current slice and disables growing at the cap", () => {
    const items = extentItems(st({ mode: "super", growLevel: 4, superN: 3 }), acts());
    expect(items.find((i) => i.id === "super3")?.active).toBe(true);
    expect(items.find((i) => i.id === "asu")?.active).toBe(false);
    expect(items.find((i) => i.id === "grow1")?.disabled).toBe(true);
    // grow-all is a closure, not a shell count: never capped by the level
    expect(items.find((i) => i.id === "growAll")?.disabled).toBeFalsy();
    expect(items.some((i) => i.id === "fuse")).toBe(true);
    // 收回 is an action: it sits in the 动作 group, right after 补全
    const ids = items.map((i) => i.id);
    expect(ids.indexOf("fuse")).toBe(ids.indexOf("complete") + 1);
  });

  it("a hand-grown copy or grow -w alone also unlocks 收回", () => {
    expect(
      extentItems(st({ mode: "cell", grown: [{ i: 3, op: "-x,-y,-z" }] }), acts()).some((i) => i.id === "fuse"),
    ).toBe(true);
    const items = extentItems(st({ complete: true }), acts());
    expect(items.some((i) => i.id === "fuse")).toBe(true);
    expect(items.find((i) => i.id === "complete")?.active).toBe(true);
    expect(items.find((i) => i.id === "asu")?.active).toBe(false);
  });

  it("radius packs centre on the selected atom and mark the active one", () => {
    const a = acts();
    const items = extentItems(
      st({ mode: "radius", packRadius: 16, packCenter: "Zn1", selectionLabel: "Zn1" }),
      a,
    );
    expect(items.find((i) => i.id === "radius16")?.active).toBe(true);
    expect(items.find((i) => i.id === "radius8")?.active).toBe(false);
    expect(items.find((i) => i.id === "radius8")?.label).toContain("Zn1");
    items.find((i) => i.id === "radius8")!.run();
    expect(a.setPackRadius).toHaveBeenCalledWith(8, "Zn1");
  });

  it("dispatches Olex2-shaped actions", () => {
    const a = acts();
    const items = extentItems(st({ mode: "cell", growLevel: 2 }), a);
    items.find((i) => i.id === "asu")!.run();
    expect(a.setMode).toHaveBeenCalledWith("asu");
    expect(a.setGrowLevel).toHaveBeenCalledWith(0);
    expect(a.setComplete).toHaveBeenCalledWith(false);
    expect(a.fuse).toHaveBeenCalled();
    items.find((i) => i.id === "grow1")!.run();
    expect(a.setGrowLevel).toHaveBeenLastCalledWith(3);
    items.find((i) => i.id === "growAll")!.run();
    expect(a.setGrowAll).toHaveBeenLastCalledWith(true);
    items.find((i) => i.id === "complete")!.run();
    expect(a.setComplete).toHaveBeenLastCalledWith(true);
    items.find((i) => i.id === "super4")!.run();
    expect(a.setMode).toHaveBeenLastCalledWith("super");
    expect(a.setSuperN).toHaveBeenCalledWith(4);
    items.find((i) => i.id === "range")!.run();
    expect(a.setPackRange).toHaveBeenCalledWith({ lo: [-0.5, -0.5, -0.5], hi: [1.5, 1.5, 1.5] });
    items.find((i) => i.id === "assemble")!.run();
    expect(a.assemble).toHaveBeenCalled();
    // the stored edge is 2: picking 超胞 2×2×2 from asu must still switch mode
    const b = acts();
    extentItems(st(), b).find((i) => i.id === "super2")!.run();
    expect(b.setMode).toHaveBeenCalledWith("super");
  });
});
