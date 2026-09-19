/** Composer quote chips (round-3 R6): the anchors found in the draft and
 * what removing one does to the text. */
import { describe, expect, it } from "vitest";
import { anchorTokens, removeAnchorToken } from "./quote";

const DRAFT =
  "请看 O 原子 O1（U_eq 0.0300 Å²）：它周围如何？ [anchor node=n0116 atoms=O1] " +
  "再看 [anchor node=n0079 atoms=N2(-x,y,-z),C3] 的环境。";

describe("anchorTokens", () => {
  it("lists every anchor with its node and atoms", () => {
    const t = anchorTokens(DRAFT);
    expect(t).toHaveLength(2);
    expect(t[0]).toEqual({ token: "[anchor node=n0116 atoms=O1]", node: "n0116", atoms: ["O1"] });
    expect(t[1].node).toBe("n0079");
    expect(t[1].atoms).toEqual(["N2(-x,y,-z)", "C3"]);
  });
  it("is empty for plain text", () => {
    expect(anchorTokens("没有引用")).toEqual([]);
  });
});

describe("removeAnchorToken", () => {
  it("removes the token and the space that joined it", () => {
    const out = removeAnchorToken(DRAFT, "[anchor node=n0116 atoms=O1]");
    expect(out).toBe(
      "请看 O 原子 O1（U_eq 0.0300 Å²）：它周围如何？ 再看 [anchor node=n0079 atoms=N2(-x,y,-z),C3] 的环境。",
    );
    expect(out).not.toContain("  ");
  });
  it("removes a leading token together with its trailing space", () => {
    expect(removeAnchorToken("[anchor node=n1] 看看", "[anchor node=n1]")).toBe("看看");
  });
  it("leaves the text alone when the token is not there", () => {
    expect(removeAnchorToken("abc", "[anchor node=n1]")).toBe("abc");
  });
});
