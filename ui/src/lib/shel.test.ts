import { describe, expect, it } from "vitest";
import { shelWorkingCutoff } from "./shel";

describe("shelWorkingCutoff", () => {
  it("reads the high-resolution limit from a SHEL card", () => {
    expect(shelWorkingCutoff("SHEL 999 1.000")).toBe(1);
    expect(shelWorkingCutoff("999 0.83")).toBe(0.83);
    expect(shelWorkingCutoff("SHEL 10 0.75")).toBe(0.75);
  });
  it("returns null when there is no usable card", () => {
    expect(shelWorkingCutoff(undefined)).toBeNull();
    expect(shelWorkingCutoff("")).toBeNull();
    expect(shelWorkingCutoff("SHEL 999")).toBeNull();
    expect(shelWorkingCutoff("SHEL 999 0")).toBeNull();
  });
});
