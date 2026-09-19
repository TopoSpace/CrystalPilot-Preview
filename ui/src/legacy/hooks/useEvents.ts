import { useEffect, useRef, useState } from "react";
import { fetchEvents, type RunEvent, type RunStatus } from "../../lib/api";

const POLL_MS = 1500;

/** Append-only event stream for a run.
 *
 * Polls `/api/runs/{id}/events?after=<cursor>` every 1.5 s while the run is
 * running. When the status settles (done/failed) one final fetch collects any
 * trailing events, then polling stops. Completed runs get a single fetch that
 * loads the full historical timeline.
 */
export function useEvents(runId: string, status: RunStatus | null): RunEvent[] {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const cursorRef = useRef(0);
  const busyRef = useRef(false);

  useEffect(() => {
    cursorRef.current = 0;
    busyRef.current = false;
    setEvents([]);
  }, [runId]);

  useEffect(() => {
    if (status === null) return; // wait until the run's status is known
    let cancelled = false;
    let timer: number | undefined;
    const ctrl = new AbortController();

    const pull = async () => {
      if (!busyRef.current) {
        busyRef.current = true;
        try {
          const res = await fetchEvents(runId, cursorRef.current, ctrl.signal);
          if (!cancelled) {
            cursorRef.current = res.next;
            if (res.events.length > 0) {
              setEvents((prev) => [...prev, ...res.events]);
            }
          }
        } catch {
          /* transient - next poll retries */
        } finally {
          busyRef.current = false;
        }
      }
      if (!cancelled && status === "running") {
        timer = window.setTimeout(() => void pull(), POLL_MS);
      }
    };
    void pull();

    return () => {
      cancelled = true;
      ctrl.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, status]);

  return events;
}
