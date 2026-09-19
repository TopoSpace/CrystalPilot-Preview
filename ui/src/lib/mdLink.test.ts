/** Deliverable-link rewriting: the traps here were found live (round 6) -
 * ReactMarkdown empties unknown URL schemes BEFORE components run, and
 * remark percent-encodes destinations so naive re-encoding double-encodes
 * spaces to %2520. */
import { describe, expect, it } from "vitest";
import { mdUrlTransform, resolveMdHref } from "./mdLink";

describe("resolveMdHref", () => {
  it("routes Linux absolute delivery paths and file URIs through the artifact endpoint", () => {
    const path = "/home/research/project/CrystalPilot Results/task/SUMMARY.md";
    const expected = "/api/wb/artifact?path=" + encodeURIComponent(path);
    expect(resolveMdHref(path.replaceAll(" ", "%20"))).toBe(expected);
    expect(resolveMdHref("file://" + path)).toBe(expected);
    expect(resolveMdHref("/api/wb/artifact?path=x")).toBe("/api/wb/artifact?path=x");
    expect(resolveMdHref("/thread/id?project=x")).toBe("/thread/id?project=x");
  });
  it("rewrites drive-letter paths to the artifact endpoint", () => {
    expect(resolveMdHref("H:\\CrystalPilot\\out\\final.cif")).toBe(
      "/api/wb/artifact?path=" +
        encodeURIComponent("H:\\CrystalPilot\\out\\final.cif"),
    );
    expect(resolveMdHref("H:/CrystalPilot/out/final.cif")).toBe(
      "/api/wb/artifact?path=" +
        encodeURIComponent("H:/CrystalPilot/out/final.cif"),
    );
  });

  it("decodes remark-encoded destinations before re-encoding (no %2520)", () => {
    const out = resolveMdHref("H:/CrystalPilot%20Results/task/final.cif");
    expect(out).toContain(encodeURIComponent("H:/CrystalPilot Results/task/final.cif"));
    expect(out).not.toContain("%2520");
  });

  it("survives a stray percent (invalid encoding)", () => {
    const out = resolveMdHref("H:/out/100%_done.cif");
    expect(out.startsWith("/api/wb/artifact?path=")).toBe(true);
  });

  it("strips file:/// prefixes", () => {
    expect(resolveMdHref("file:///H:/out/final.cif")).toBe(
      "/api/wb/artifact?path=" + encodeURIComponent("H:/out/final.cif"),
    );
  });

  it("leaves web URLs alone", () => {
    expect(resolveMdHref("https://example.org/x")).toBe(
      "https://example.org/x",
    );
    expect(resolveMdHref("#anchor")).toBe("#anchor");
  });
});

describe("mdUrlTransform", () => {
  it("rescues local paths that the default sanitizer would empty", () => {
    const out = mdUrlTransform("H:/CrystalPilot/out/final.cif");
    expect(out).toContain("/api/wb/artifact?path=");
  });

  it("still sanitizes dangerous schemes", () => {
    expect(mdUrlTransform("javascript:alert(1)")).toBe("");
  });

  it("passes https through", () => {
    expect(mdUrlTransform("https://example.org/a?b=c")).toBe(
      "https://example.org/a?b=c",
    );
  });
});
