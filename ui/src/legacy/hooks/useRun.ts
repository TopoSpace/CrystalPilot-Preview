import { useEffect, useState } from "react";
import { fetchRun, type RunDetail } from "../../lib/api";

const POLL_MS = 2000;
const RETRY_MS = 4000;

/** Poll run detail while the run is in flight; stop once it is done/failed. */
export function useRun(runId: string): {
  run: RunDetail | null;
  error: string | null;
} {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRun(null);
    setError(null);
    let cancelled = false;
    let timer: number | undefined;
    const ctrl = new AbortController();

    const tick = async () => {
      try {
        const detail = await fetchRun(runId, ctrl.signal);
        if (cancelled) return;
        setRun(detail);
        setError(null);
        if (detail.status === "running") {
          timer = window.setTimeout(() => void tick(), POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        // Retry transient failures; an unknown run will never appear.
        if (!/unknown run/i.test(msg)) {
          timer = window.setTimeout(() => void tick(), RETRY_MS);
        }
      }
    };
    void tick();

    return () => {
      cancelled = true;
      ctrl.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId]);

  return { run, error };
}
