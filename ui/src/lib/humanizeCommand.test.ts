import { describe, expect, it } from "vitest";
import { humanizeCommand, unwrapCommand } from "./humanizeCommand";
import { commandGlyph } from "./activityIcons";

// real wrapper shapes captured from r11 case-c transcripts
const PS = String.raw`"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command `;

describe("unwrapCommand", () => {
  it("strips the powershell -Command wrapper and outer quotes", () => {
    expect(unwrapCommand(`${PS}"Get-Content job.lst"`)).toBe(
      "Get-Content job.lst",
    );
    expect(unwrapCommand(`${PS}'$p = 1; dir'`)).toBe("$p = 1; dir");
  });

  it("strips cmd /c", () => {
    expect(unwrapCommand('cmd /d /s /c "shelxl job"')).toBe("shelxl job");
  });

  it("passes plain commands through", () => {
    expect(unwrapCommand("shelxl job")).toBe("shelxl job");
  });

  it("recognizes the actual executable in Linux and Windows wrappers", () => {
    expect(commandGlyph('/bin/bash -lc "/opt/shelx/shelxt job"')).toBe("solve");
    expect(commandGlyph(`${PS}"& 'H:\\vendor\\shelx\\shelxl.exe' job"`)).toBe("refine");
    expect(commandGlyph("dials.integrate indexed.expt")).toBe("integration");
    expect(commandGlyph("cat shelxl.log")).toBe("book");
    expect(commandGlyph("rg shelxt setup.py")).toBe("search");
    expect(commandGlyph(`python -c 'print("shelxt job; shelxl job")'`)).toBe("terminal");
    expect(commandGlyph("unknown-tool shelxt job")).toBe("terminal");
  });
});

describe("humanizeCommand", () => {
  it("labels crystallography executables", () => {
    const h = humanizeCommand(`${PS}"& 'H:\\vendor\\shelx\\shelxl.exe' job"`);
    expect(h.label).toContain("SHELXL");
    expect(h.recognized).toBe(true);
  });

  it("labels PS cmdlets with the file object", () => {
    const h = humanizeCommand(`${PS}"Get-Content -LiteralPath 'H:\\x\\job.lst' -Tail 40"`);
    expect(h.label).toBe("读取文件 · job.lst");
  });

  it("skips $var assignment to find the actor (real case-c shape)", () => {
    const h = humanizeCommand(
      `${PS}'$p = Resolve-Path -LiteralPath ".crystalpilot"; Get-ChildItem $p -File'`,
    );
    expect(h.recognized).toBe(true);
    // first statement's actor is Resolve-Path
    expect(h.label).toContain("解析路径");
  });

  it("labels python -m crystalpilot invocations", () => {
    const h = humanizeCommand(
      `${PS}"& 'H:\\CrystalPilot\\.venv\\Scripts\\python.exe' -X utf8 -m crystalpilot.cli brief"`,
    );
    expect(h.label).toContain("CrystalPilot");
  });

  it("labels dials wrappers by stage", () => {
    const h = humanizeCommand("dials.find_spots imported.expt");
    expect(h.label).toContain("DIALS");
    expect(h.label).toContain("find_spots");
  });

  it("degrades unknown commands to a trimmed head, never empty", () => {
    const h = humanizeCommand(`${PS}"someweirdtool --flag value"`);
    expect(h.recognized).toBe(false);
    expect(h.label).toContain("运行命令：");
    expect(h.label.length).toBeGreaterThan(6);
  });
});
