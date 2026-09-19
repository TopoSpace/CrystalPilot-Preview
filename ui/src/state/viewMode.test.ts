/** P1-6 display-density persistence: junk values and blocked storage must
 * both fall back to 简洁 (concise) - the safe default for non-programmer
 * users; only an explicit "verbose" round-trips. */
import { describe, expect, it } from "vitest";
import { loadViewMode, saveViewMode, type KVStore } from "./ViewMode";

function memStore(): KVStore & { map: Map<string, string> } {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
  };
}

describe("viewMode persistence", () => {
  it("defaults to concise on empty storage", () => {
    expect(loadViewMode(memStore())).toBe("concise");
  });

  it("round-trips verbose and back", () => {
    const s = memStore();
    saveViewMode("verbose", s);
    expect(loadViewMode(s)).toBe("verbose");
    saveViewMode("concise", s);
    expect(loadViewMode(s)).toBe("concise");
  });

  it("treats junk stored values as concise", () => {
    const s = memStore();
    s.map.set("cp.viewMode", "ultra-detailed");
    expect(loadViewMode(s)).toBe("concise");
  });

  it("survives a throwing storage (privacy mode)", () => {
    const bomb: KVStore = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    expect(loadViewMode(bomb)).toBe("concise");
    expect(() => saveViewMode("verbose", bomb)).not.toThrow();
  });

  it("survives absent storage (null)", () => {
    expect(loadViewMode(null)).toBe("concise");
    expect(() => saveViewMode("verbose", null)).not.toThrow();
  });
});
