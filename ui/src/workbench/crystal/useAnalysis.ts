import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRefineAnalysis, pollRefineAnalysis, releaseRefineAnalysis, startRefineAnalysis } from "../../lib/wbApi";
import type { AnalysisJob, AnalysisResponse } from "../../lib/wbTypes";

export interface AnalysisState {
  kind: "idle" | "loading" | "loaded" | "error";
  data: AnalysisResponse | null;
  job: AnalysisJob | null;
  message: string | null;
}

const EMPTY: AnalysisState = { kind: "idle", data: null, job: null, message: null };

export function analysisRunning(job: AnalysisJob | null): boolean {
  return job !== null && ["queued", "running", "cancelling"].includes(job.status);
}

/** Conditional polls carry stage metadata but omit an unchanged large result. */
export function foldAnalysisJob(previous: AnalysisState, job: AnalysisJob): AnalysisState {
  const sameJob = previous.job?.job_id === job.job_id;
  if (sameJob && previous.job!.revision > job.revision) return previous;
  const data = job.result ?? (sameJob ? previous.data : null);
  return { kind: data ? "loaded" : "loading", data, job, message: null };
}

export function useAnalysis(project: string | null, node: string | null) {
  const [state, setState] = useState<AnalysisState>(EMPTY);
  const [tick, setTick] = useState(0);
  const [paused, setPaused] = useState(false);
  const [stopping, setStopping] = useState(false);
  const key = `${project ?? ""}|${node ?? ""}`;
  const keyRef = useRef(key);
  keyRef.current = key;
  const current = useRef<{ project: string; job: string; observer: string; key: string } | null>(null);

  useEffect(() => { setPaused(false); }, [key]);
  useEffect(() => {
    if (!project || !node) {
      setState(EMPTY);
      return undefined;
    }
    if (paused) return undefined;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attachment: { job: string; observer: string } | null = null;
    setState({ ...EMPTY, kind: "loading" });
    const accept = (job: AnalysisJob) => {
      if (controller.signal.aborted) return;
      setState((previous) => foldAnalysisJob(previous, job));
      if (analysisRunning(job)) timer = setTimeout(() => void poll(job), 800);
    };
    const fail = (error: unknown) => {
      if (!controller.signal.aborted) setState((previous) => ({ ...previous,
        kind: previous.data ? "loaded" : "error",
        message: error instanceof Error ? error.message : String(error) }));
    };
    const poll = async (job: AnalysisJob) => {
      try {
        accept(await pollRefineAnalysis(project, job.job_id, job.result_revision, controller.signal));
      } catch (error) { fail(error); }
    };
    void startRefineAnalysis(project, node, undefined, controller.signal)
      .then((job) => {
        if (job.observer_id) {
          attachment = { job: job.job_id, observer: job.observer_id };
          if (controller.signal.aborted) {
            void releaseRefineAnalysis(project, attachment.job, attachment.observer).catch(() => undefined);
            return;
          }
          current.current = { project, ...attachment, key };
        }
        accept(job);
      }).catch(fail);
    // Leaving the view releases its observer, not the shared calculation.
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
      if (attachment) void releaseRefineAnalysis(project, attachment.job, attachment.observer).catch(() => undefined);
    };
  }, [project, node, tick, paused, key]);

  const retry = useCallback(() => { setPaused(false); setTick((value) => value + 1); }, []);
  const stop = useCallback(async () => {
    const handle = current.current;
    if (!handle || handle.key !== keyRef.current || stopping) return;
    setStopping(true);
    try {
      const job = await cancelRefineAnalysis(handle.project, handle.job, handle.observer);
      if (keyRef.current === handle.key) {
        setState((previous) => foldAnalysisJob(previous, job));
        setPaused(true);
      }
    } catch (error) {
      if (keyRef.current === handle.key) setState((previous) => ({ ...previous,
        message: error instanceof Error ? error.message : String(error) }));
    } finally { setStopping(false); }
  }, [stopping]);

  return { state, paused, stopping, retry, stop };
}
