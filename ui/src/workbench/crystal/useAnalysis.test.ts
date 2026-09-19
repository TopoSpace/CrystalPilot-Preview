import { describe, expect, it } from "vitest";
import type { AnalysisJob, AnalysisResponse } from "../../lib/wbTypes";
import { analysisRunning, foldAnalysisJob, type AnalysisState } from "./useAnalysis";

const data = { node: "n0001", v: 7, voids_v: 6, interactions: null, pores: null,
  topology: null, guests: null } as AnalysisResponse;
const job = (over: Partial<AnalysisJob> = {}): AnalysisJob => ({ job_id: "j1", node: "n0001",
  revision: 2, result_revision: 2, status: "running", result: data, ...over } as AnalysisJob);
const empty: AnalysisState = { kind: "loading", data: null, job: null, message: null };

describe("progressive analysis state", () => {
  it("keeps completed blocks during metadata-only polls", () => {
    const state = foldAnalysisJob(empty, job());
    const next = foldAnalysisJob(state, job({ result: null, elapsed_s: 100 }));
    expect(next.data).toBe(data);
    expect(next.job?.elapsed_s).toBe(100);
  });

  it("does not reuse data for another job or node", () => {
    const state = foldAnalysisJob(empty, job());
    expect(foldAnalysisJob(state, job({ job_id: "j2", result: null })).data).toBeNull();
  });

  it("does not let an older poll undo a cancellation", () => {
    const state = foldAnalysisJob(empty, job({ revision: 5, status: "cancelling" }));
    expect(foldAnalysisJob(state, job({ revision: 4 }))).toBe(state);
  });

  it("keeps failed sections null instead of fabricating empty results", () => {
    const state = foldAnalysisJob(empty, job({ status: "partial" }));
    expect(state.data?.pores).toBeNull();
    expect(state.kind).toBe("loaded");
    expect(analysisRunning(state.job)).toBe(false);
  });

  it("continues observing a C routine while cancellation is pending", () => {
    expect(analysisRunning(job({ status: "cancelling" }))).toBe(true);
    expect(analysisRunning(job({ status: "cancelled" }))).toBe(false);
  });
});
