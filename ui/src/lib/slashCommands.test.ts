import { describe, expect, it } from "vitest";
import {
  filterSlash,
  parseSlash,
  resolveSlash,
  slashActive,
  SLASH_COMMANDS,
} from "./slashCommands";

describe("slash commands", () => {
  it("parses a command line with arguments", () => {
    expect(parseSlash("/rename  My cage  ")).toEqual({ name: "rename", args: "My cage" });
    expect(parseSlash("/compact")).toEqual({ name: "compact", args: "" });
    expect(parseSlash("hello")).toBeNull();
    expect(parseSlash("/model\nsecond line")).toBeNull();
  });

  it("filters by prefix on names and aliases", () => {
    expect(filterSlash("/")).toEqual(SLASH_COMMANDS);
    expect(filterSlash("/mo").map((c) => c.name)).toEqual(["model"]);
    expect(filterSlash("/appr").map((c) => c.name)).toEqual(["permissions"]);
    expect(filterSlash("/zzz")).toEqual([]);
  });

  it("resolves aliases and reports command mode", () => {
    expect(resolveSlash("approvals")?.name).toBe("permissions");
    expect(resolveSlash("nope")).toBeNull();
    expect(slashActive("/")).toBe(true);
    expect(slashActive("/com")).toBe(true);
    expect(slashActive("/rename x")).toBe(false);
    expect(slashActive("x")).toBe(false);
  });

  it("mirrors the Codex CLI vocabulary", () => {
    const names = new Set(SLASH_COMMANDS.map((c) => c.name));
    for (const n of ["model", "permissions", "compact", "status", "mcp", "skills", "new", "rename"]) {
      expect(names.has(n)).toBe(true);
    }
    expect(new Set(SLASH_COMMANDS.map((c) => c.name)).size).toBe(SLASH_COMMANDS.length);
  });
});
