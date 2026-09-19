import { describe, expect, it } from "vitest";
import { groupArtifacts, markFor, taskDirOf } from "./delivery";
import type { ArtifactEntry } from "./wbTypes";

const BS = String.fromCharCode(92);
const ROOT = `H:${BS}c${BS}mof${BS}CrystalPilot Results${BS}task_20260905_151009`;
const art = (rel: string): ArtifactEntry => ({ rel, path: `${ROOT}${BS}${rel}`, size: 10 });

describe("artifacts grouped by delivery", () => {
  const list = [
    art("SUMMARY.md"),
    art("final.res"),
    art("checkcif.json"),
    art("final.cif"),
    art(`command_output${BS}call_1.txt`),
    art(`whole-guest-study${BS}final.cif`),
    art(`whole-guest-study${BS}notes.md`),
    art(`guest-location-update${BS}final.res`),
    art("transcript.jsonl"),
  ];

  it("puts the top-level delivery first, sub-deliveries by name, logs apart", () => {
    const { groups, logs } = groupArtifacts(list);
    expect(groups.map((g) => g.dir)).toEqual(["", "guest-location-update", "whole-guest-study"]);
    expect(logs.map((a) => a.rel)).toEqual([`command_output${BS}call_1.txt`, "transcript.jsonl"]);
  });

  it("leads each group with the main files in the canonical order", () => {
    const { groups } = groupArtifacts(list);
    expect(groups[0].main.map((a) => a.rel)).toEqual(["final.cif", "final.res", "SUMMARY.md"]);
    expect(groups[0].rest.map((a) => a.rel)).toEqual(["checkcif.json"]);
    expect(groups[2].main.map((a) => a.rel)).toEqual([`whole-guest-study${BS}final.cif`]);
    expect(groups[2].rest.map((a) => a.rel)).toEqual([`whole-guest-study${BS}notes.md`]);
  });

  it("recovers the task directory and matches the manifest behind a group", () => {
    expect(taskDirOf(art(`whole-guest-study${BS}final.cif`))).toBe("task_20260905_151009");
    expect(taskDirOf({ rel: "x.cif", path: "somewhere/else.cif", size: 1 })).toBeNull();
    const { groups } = groupArtifacts(list);
    const marks = [
      { node: "n0070", status: "diagnostic", rel: "task_20260905_151009" },
      { node: "n0224", status: "provisional", rel: "task_20260905_151009/whole-guest-study" },
      { node: "n0001", status: "final", rel: "task_other" },
    ];
    expect(markFor(groups[0], marks)?.node).toBe("n0070");
    expect(markFor(groups[2], marks)?.node).toBe("n0224");
    expect(markFor(groups[1], marks)).toBeNull();
  });
});
