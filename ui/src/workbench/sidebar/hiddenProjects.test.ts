import { describe, expect, it } from "vitest";
import { hideKey, isScratchProject, splitRecent } from "./hiddenProjects";

describe("recent projects fold", () => {
  it("keys paths case- and separator-insensitively", () => {
    expect(hideKey("H:\\CrystalPilot-campaigns\\Reg2\\")).toBe("h:/crystalpilot-campaigns/reg2");
    expect(hideKey("h:/CrystalPilot-campaigns/reg2")).toBe("h:/crystalpilot-campaigns/reg2");
  });

  it("treats ui-import-<epoch> as scratch unless it was named", () => {
    expect(isScratchProject("H:\\x\\ui-import-1788590415165")).toBe(true);
    expect(isScratchProject("H:\\x\\ui-import-1788590415165", "MOF-5 试导入")).toBe(false);
    expect(isScratchProject("H:\\x\\pe8f898bd")).toBe(false);
    expect(isScratchProject("H:\\x\\ui-import-abc")).toBe(false);
  });

  it("folds scratch and hidden rows under 更多 and caps the main list", () => {
    const rows = [
      { path: "H:\\c\\mof", display_name: "Zr-MOF" },
      { path: "H:\\c\\ui-import-1788590415165", display_name: null },
      { path: "H:\\c\\pe8f898bd", display_name: null },
      { path: "H:\\c\\cage", display_name: null },
      { path: "H:\\c\\old", display_name: null },
    ];
    const { primary, more } = splitRecent(rows, new Set([hideKey("h:/c/pe8f898bd")]), 2);
    expect(primary.map((r) => r.path)).toEqual(["H:\\c\\mof", "H:\\c\\cage"]);
    // overflow first (still real projects), then scratch, then hidden - in list order
    expect(more.map((r) => r.path)).toEqual([
      "H:\\c\\old",
      "H:\\c\\ui-import-1788590415165",
      "H:\\c\\pe8f898bd",
    ]);
  });
});
