/** Round-2 evidence D20: the turn digest printed "R1 0.2293→-13.4000"
 * because validate_structure's score breakdown (penalty points keyed r1 /
 * goof) was parsed as model metrics. The shapes below are copied from real
 * workbench transcripts (reg8-nm, 2026-09-04). */
import { describe, expect, it } from "vitest";
import { safeParseResultTail, stripNonMetricContainers } from "./resultTail";

const VALIDATE = {
  ok: true,
  summary: {
    n_alerts: 0,
    alerts: [],
    system_type: "molecular",
    framework_dimensionality: 0,
    confidence: {
      score: 86.6,
      grade: "high",
      system_type: "molecular",
      criteria: "molecular criteria: 0-D expected - periodicity is NOT required",
      breakdown: { r1: -13.4, goof: 0.0, diff_map: 0.0, alerts: 0 },
    },
    composition_deviation: null,
    asu_sanity: { n_detached_atoms: 0 },
  },
};

const REFINE = {
  ok: true,
  summary: {
    node: "n0002",
    branch: "main",
    label: "P-1 isotropic consolidation",
    r1_strong: 0.2293,
    r1_all: 0.2381,
    wr2: 0.6465,
    goof: 5.887,
    n_params: 92,
    n_reflections: 3046,
    diff_map_max: 1.2,
    history: [{ r1_strong: 0.31, wr2: 0.7, goof: 7.1 }],
  },
};

const COMPARE = {
  ok: true,
  summary: {
    a: { node: "n0019", metrics: { r1_strong: 0.0948, wr2: 0.3049, goof: 1.41 } },
    b: { node: "n0024", metrics: { r1_strong: 0.082, wr2: 0.2828, goof: 1.314 } },
    delta_b_minus_a: { r1_strong: -0.0128, wr2: -0.0221, goof: -0.096 },
  },
};

describe("safeParseResultTail (JSON path)", () => {
  it("does not read validate_structure's score breakdown as metrics", () => {
    const s = safeParseResultTail(JSON.stringify(VALIDATE));
    expect(s?.ok).toBe(true);
    expect(s?.r1).toBeUndefined();
    expect(s?.goof).toBeUndefined();
    expect(s?.wr2).toBeUndefined();
  });

  it("still reads a refine result (and skips the history array)", () => {
    const s = safeParseResultTail(JSON.stringify(REFINE));
    expect(s?.node).toBe("n0002");
    expect(s?.r1).toBe(0.2293);
    expect(s?.wr2).toBe(0.6465);
    expect(s?.goof).toBe(5.887);
    expect(s?.nParams).toBe(92);
    expect(s?.diffMapMax).toBe(1.2);
  });

  it("still finds run_shelxl's nested summary.shelxl block", () => {
    const s = safeParseResultTail(
      JSON.stringify({ ok: true, summary: { shelxl: { r1_strong: 0.0948, wr2: 0.3049, goof: 1.41 } } }),
    );
    expect(s?.r1).toBe(0.0948);
    expect(s?.goof).toBe(1.41);
  });

  it("never takes a compare_nodes delta as an R factor", () => {
    const s = safeParseResultTail(JSON.stringify(COMPARE));
    expect(s?.r1).not.toBeLessThan(0);
    expect(s?.r1).toBe(0.0948);
  });

  it("drops out-of-range look-alikes: percent R1 and zero GooF", () => {
    const s = safeParseResultTail(JSON.stringify({ ok: true, summary: { r1: 22.9, wr2: 1.5, goof: 0 } }));
    expect(s?.r1).toBeUndefined();
    expect(s?.wr2).toBeUndefined();
    expect(s?.goof).toBeUndefined();
  });
});

describe("safeParseResultTail (truncated tail, regex path)", () => {
  // head-truncated: JSON.parse fails, regex fallback runs
  const TAIL =
    '"r1_strong": 0.0948, "goof": 1.41, "confidence": {"score": 86.6, "grade": "hi{gh}", ' +
    '"breakdown": {"r1": -13.4, "goof": 0.0, "alerts": 0}}, "asu_sanity": {"n_detached_atoms": 0}}';

  it("strips score containers before matching", () => {
    const stripped = stripNonMetricContainers(TAIL);
    expect(stripped).not.toContain("-13.4");
    expect(stripped).toContain('"n_detached_atoms": 0');
    const s = safeParseResultTail(TAIL);
    expect(s?.r1).toBe(0.0948);
    expect(s?.goof).toBe(1.41);
  });

  it("yields no metrics when only a breakdown is present", () => {
    const s = safeParseResultTail('"confidence": {"breakdown": {"r1": -13.4, "goof": 0.0}}, "x": 1}');
    expect(s?.r1).toBeUndefined();
    expect(s?.goof).toBeUndefined();
  });

  it("swallows an unterminated container (tail cut inside it)", () => {
    const s = safeParseResultTail('"goof": 1.62, "delta_b_minus_a": {"r1_strong": -0.01, "goof": -0.2');
    expect(s?.goof).toBe(1.62);
    expect(s?.r1).toBeUndefined();
  });

  it("range-checks the regex path too", () => {
    const s = safeParseResultTail('"r1": -0.5, "goof": 0.0, "wr2": 0.31}');
    expect(s?.r1).toBeUndefined();
    expect(s?.goof).toBeUndefined();
    expect(s?.wr2).toBe(0.31);
  });
});
