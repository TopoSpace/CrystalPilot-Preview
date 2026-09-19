import { describe, expect, it } from "vitest";
import type { ArtifactEntry } from "./wbTypes";
import {
  cifGradeLabel,
  deliveryArtifacts,
  deliveryFacts,
  deliveryStatusLabel,
  isDeliverable,
  mainFiles,
} from "./delivery";

const art = (rel: string): ArtifactEntry => ({
  rel,
  path: `H:\\p\\CrystalPilot Results\\task\\${rel}`,
  size: 10,
});

describe("deliverables", () => {
  it("keeps the product files and drops run logs", () => {
    expect(isDeliverable("final.cif")).toBe(true);
    expect(isDeliverable("checkcif_alerts.md")).toBe(true);
    expect(isDeliverable("command_output\\call_x.txt")).toBe(false);
    expect(isDeliverable("command_output/call_x.txt")).toBe(false);
    expect(isDeliverable("transcript.jsonl")).toBe(false);
    expect(isDeliverable("state.json.tmp123-4")).toBe(false);
    const all = [
      "final.cif",
      "final.fcf",
      "final.res",
      "SUMMARY.md",
      "transcript.jsonl",
      "command_output\\a.txt",
      "REPORT.json",
    ].map(art);
    expect(deliveryArtifacts(all).map((a) => a.rel)).toEqual([
      "final.cif",
      "final.fcf",
      "final.res",
      "SUMMARY.md",
      "REPORT.json",
    ]);
  });

  it("lists the main files in reading order with their artifacts when known", () => {
    const files = [
      "OLEX2_CHECK.log",
      "SUMMARY.md",
      "final.res",
      "final.hkl",
      "final.ins",
      "final.cif",
      "final.fcf",
      "final.p4p",
      "VALIDATION.md",
    ];
    const arts = ["final.cif", "SUMMARY.md"].map(art);
    const main = mainFiles(files, arts);
    expect(main.map((m) => m.name)).toEqual([
      "final.cif",
      "final.fcf",
      "final.res",
      "final.ins",
      "final.hkl",
      "final.p4p",
      "SUMMARY.md",
      "VALIDATION.md",
    ]);
    expect(main[0].artifact?.rel).toBe("final.cif");
    expect(main[1].artifact).toBeNull();
  });

  it("names the CIF grade and the hand-over state from the tool summaries", () => {
    const write = {
      ok: true,
      summary: {
        status: "diagnostic",
        files: ["final.res", "final.cif", "final.ins", "final.hkl"],
        cif_grade: "model",
        manual_continuation: {
          ready: true,
          missing: ["final.p4p"],
          notes: ["final.p4p: no .p4p on record"],
        },
      },
    };
    const f = deliveryFacts(write, undefined);
    expect(f.cifGrade).toBe("model");
    expect(cifGradeLabel(f.cifGrade)).toBe("模型 CIF");
    expect(cifGradeLabel("shelxl-acta")).toBe("SHELXL ACTA CIF");
    expect(f.handover).toEqual({
      ready: true,
      missing: ["final.p4p"],
      notes: ["final.p4p: no .p4p on record"],
    });
    // finalize wins when it re-evaluated the directory
    const fin = {
      ok: true,
      summary: {
        status: "diagnostic",
        manual_continuation: { ready: false, missing: ["final.fab"], notes: [] },
      },
    };
    expect(deliveryFacts(write, fin).handover?.missing).toEqual(["final.fab"]);
  });

  it("labels the status in Chinese and keeps unknown values verbatim", () => {
    expect(deliveryStatusLabel("final")).toBe("定稿");
    expect(deliveryStatusLabel("provisional")).toBe("暂定");
    expect(deliveryStatusLabel("diagnostic")).toBe("诊断性");
    expect(deliveryStatusLabel("weird")).toBe("weird");
    expect(deliveryStatusLabel(null)).toBe("");
  });
});

describe("deliveryFacts (real org_hsl payload shapes)", () => {
  const write = {
    ok: true,
    summary: {
      output_dir: "H:\\p\\CrystalPilot Results\\task_1",
      status: "provisional",
      files: [
        "final.res",
        "final.cif",
        "REPORT.json",
        "final.fcf",
        "MANIFEST.json",
      ],
      final_node: "n0013",
      source_state: { node: "n0013", revision: 14 },
      metrics: {
        r1_strong: 0.0263,
        r1_all: 0.0273,
        wr2: 0.0688,
        goof: 1.035,
        n_params: -1,
      },
    },
  };
  const fin = {
    ok: true,
    summary: {
      output_dir: "H:\\p\\CrystalPilot Results\\task_1",
      status: "final",
      sealed: true,
      files: [
        "SUMMARY.md",
        "VALIDATION.md",
        "final.cif",
        "final.fcf",
        "final.res",
        "transcript.jsonl",
        "MANIFEST.json",
      ],
      waived: [{ item: "alert:183_A" }, { item: "alert:184_A" }],
    },
  };

  it("finalize wins on status and files; write_outputs supplies node and metrics", () => {
    const f = deliveryFacts(write, fin);
    expect(f.status).toBe("final");
    expect(f.waived).toBe(2);
    expect(f.node).toBe("n0013");
    expect(f.metrics).toEqual({ r1: 0.0263, wr2: 0.0688, goof: 1.035 });
    expect(f.files).toContain("SUMMARY.md");
    expect(f.outputDir).toBe("H:\\p\\CrystalPilot Results\\task_1");
  });

  it("copes with a missing finalize (write_outputs only) and with garbage", () => {
    const f = deliveryFacts(write, undefined);
    expect(f.status).toBe("provisional");
    expect(f.files).toEqual([
      "final.res",
      "final.cif",
      "REPORT.json",
      "final.fcf",
      "MANIFEST.json",
    ]);
    const g = deliveryFacts("nonsense", 42);
    expect(g).toEqual({
      status: null,
      waived: 0,
      node: null,
      metrics: null,
      files: [],
      outputDir: null,
      cifGrade: null,
      handover: null,
    });
  });
});
