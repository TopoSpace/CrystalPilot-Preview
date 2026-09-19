/** EventSource lifecycle for one thread channel.
 *
 * bootstrap (GET transcript) -> EventSource(after=live_cursor) -> live.
 * The transcript snapshot carries the live channel's cursor and generation
 * token; SSE resumes from that cursor, and the channel_hello that opens
 * every connection is compared against the token: a different generation
 * means the server-side channel (and its seq numbering) was recreated, so
 * the client re-bootstraps instead of trusting Last-Event-ID (round-3 R1,
 * forensics F-2). Deltas (agent_delta / command_output) accumulate in
 * buffers - command output per codex item id, because commands run
 * concurrently - and flush once per animation frame as a single `stream`
 * action; any non-delta event flushes pending deltas FIRST so ordering is
 * preserved.
 *
 * Self-healing (2026-09-16, "the page silently stops updating until a
 * reload"):
 * - a non-2xx reply ends an EventSource for good (readyState CLOSED, no
 *   browser retry): recover at once instead of waiting for a second error
 *   that never comes (the old ladder sat on "正在重新连接…" forever after a
 *   server restart or after the idle reaper released the project);
 * - the server sends a `ping` data event every ~15 s (SSE comments never
 *   reach JavaScript): STALE_AFTER_MS of silence means the socket is dead
 *   (sleep, network change, half-open TCP) and the channel is rebuilt;
 * - `channel_closed` (project session released) and a channel_hello whose
 *   buffer no longer holds our resume point both trigger a full re-sync;
 * - visibilitychange -> visible and window `online` reconcile against the
 *   server: dead/stale socket -> recover; otherwise a one-line transcript
 *   snapshot is compared to what we hold (generation, cursor) and any gap
 *   re-bootstraps.
 *
 * Failure ladder: transient errors let the browser auto-reconnect (the server
 * sends `retry: 2000`, and Last-Event-ID resumes the same channel). If errors
 * persist > RECOVERY_AFTER_MS, full recovery: POST projects/open (idempotent),
 * re-fetch the transcript (bootstrap reset), and open a FRESH EventSource with
 * after=<snapshot cursor> - never reuse the failed one, whose stale
 * Last-Event-ID would poison a restarted channel whose seq reset to 0.
 */
import { useEffect, type Dispatch } from "react";
import { eventsUrl, getTranscript, openProject } from "../lib/wbApi";
import type { ChannelHelloEvent, WbEvent } from "../lib/wbTypes";
import type { ThreadAction } from "./threadReducer";

export const RECOVERY_AFTER_MS = 5000;
export const RECOVERY_RETRY_MS = 8000;
/** the server pings every ~15 s; this much silence = dead socket */
export const STALE_AFTER_MS = 45_000;
const WATCHDOG_MS = 10_000;
/** a hidden tab has no animation frames: flush deltas on a timer instead */
const HIDDEN_FLUSH_MS = 250;

/** Debug/e2e window: the live status of the channel hook, per thread. */
export interface ChannelProbe {
  status: string;
  lastMessageAt: number;
  connects: number;
  recoveries: number;
  reconciles: number;
}

declare global {
  interface Window {
    __cpChannel?: Record<string, ChannelProbe>;
  }
}

function probe(threadId: string, patch: Partial<ChannelProbe>): void {
  if (typeof window === "undefined") return;
  const all = (window.__cpChannel ??= {});
  const cur = all[threadId] ?? {
    status: "connecting",
    lastMessageAt: 0,
    connects: 0,
    recoveries: 0,
    reconciles: 0,
  };
  all[threadId] = { ...cur, ...patch };
}

export function useThreadChannel(
  threadId: string,
  project: string | null,
  dispatch: Dispatch<ThreadAction>,
): void {
  useEffect(() => {
    if (!threadId) return undefined;
    let disposed = false;
    let es: EventSource | null = null;
    let raf = 0;
    let hiddenTimer: number | undefined;
    let agentBuf = "";
    // command output per codex item id ("" = no id on the wire), in the
    // order the first chunk of each arrived
    let commandBufs = new Map<string, string>();
    let firstErrorAt: number | null = null;
    let recovering = false;
    let retryTimer: number | undefined;
    // numbering the last transcript snapshot belonged to, and where to
    // resume the live channel
    let generation: string | null = null;
    let resumeAfter = 0;
    // last seq seen on the wire (for the reconcile gap check)
    let lastSeq = 0;
    let lastMessageAt = Date.now();
    let status = "connecting";

    const setStatus = (s: "connecting" | "live" | "reconnecting" | "recovering" | "dead"): void => {
      status = s;
      probe(threadId, { status: s });
      dispatch({ type: "channel", status: s });
    };

    const flush = (): void => {
      raf = 0;
      if (hiddenTimer !== undefined) {
        window.clearTimeout(hiddenTimer);
        hiddenTimer = undefined;
      }
      if (agentBuf === "" && commandBufs.size === 0) return;
      const action: ThreadAction = { type: "stream" };
      if (agentBuf !== "") action.agentDelta = agentBuf;
      if (commandBufs.size > 0) {
        action.commandDeltas = [...commandBufs.entries()].map(([k, delta]) => ({
          itemId: k === "" ? null : k,
          delta,
        }));
      }
      agentBuf = "";
      commandBufs = new Map();
      dispatch(action);
    };

    const scheduleFlush = (): void => {
      if (raf !== 0 || hiddenTimer !== undefined) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        // requestAnimationFrame is paused in background tabs; the buffer
        // would otherwise wait for the next non-delta event
        hiddenTimer = window.setTimeout(flush, HIDDEN_FLUSH_MS);
      } else {
        raf = requestAnimationFrame(flush);
      }
    };

    const flushNow = (): void => {
      if (raf !== 0) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
      flush();
    };

    const bootstrap = async (): Promise<void> => {
      let events: WbEvent[] = [];
      let page: { total: number | null; oldestEid: number | null; hasMore: boolean } = {
        total: null,
        oldestEid: null,
        hasMore: false,
      };
      let gen: string | null = null;
      let cursor = 0;
      let busy: boolean | undefined;
      try {
        const t = await getTranscript(threadId, project ?? undefined);
        events = t.events;
        gen = t.generation ?? null;
        cursor = t.live_cursor ?? 0;
        busy = typeof t.busy === "boolean" ? t.busy : undefined;
        page = {
          total: t.total ?? null,
          oldestEid: t.oldest_eid ?? null,
          hasMore: t.has_more === true,
        };
      } catch {
        // missing / 404 -> start from an empty transcript
      }
      if (disposed) return;
      generation = gen;
      resumeAfter = cursor;
      lastSeq = cursor;
      dispatch({ type: "bootstrap", events, reset: true, page, generation: gen, cursor, busy });
    };

    const scheduleRecover = (delayMs: number): void => {
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined;
        void recover();
      }, delayMs);
    };

    const connect = (): void => {
      if (disposed) return;
      es?.close();
      agentBuf = "";
      commandBufs = new Map();
      lastMessageAt = Date.now();
      probe(threadId, { connects: (window.__cpChannel?.[threadId]?.connects ?? 0) + 1 });
      es = new EventSource(eventsUrl(threadId, resumeAfter, project));
      const mine = es;
      mine.onopen = () => {
        if (mine !== es) return;
        firstErrorAt = null;
        lastMessageAt = Date.now();
        probe(threadId, { lastMessageAt });
        setStatus("live");
      };
      mine.onmessage = (e: MessageEvent<string>) => {
        if (mine !== es) return;
        firstErrorAt = null;
        lastMessageAt = Date.now();
        probe(threadId, { lastMessageAt });
        let ev: WbEvent;
        try {
          ev = JSON.parse(e.data) as WbEvent;
        } catch {
          return;
        }
        if (!ev || typeof ev !== "object" || !("kind" in ev)) return;
        if (ev.kind === "ping") return;
        if (ev.kind === "channel_closed") {
          // the project session was released server-side: its channel is
          // gone, the next one has a new generation
          void recover();
          return;
        }
        if (ev.kind === "channel_hello") {
          const hello = ev as ChannelHelloEvent;
          if (generation !== null && hello.generation !== generation) {
            // the channel was recreated (project reopened / server
            // restarted): its seq restarted, our cursor is meaningless
            generation = hello.generation;
            void recover();
            return;
          }
          generation = hello.generation;
          if (
            typeof hello.oldest === "number" &&
            hello.after > 0 &&
            hello.oldest > hello.after + 1
          ) {
            // events between our resume point and the oldest buffered seq
            // fell out of the server buffer: replay cannot fill the gap
            void recover();
          }
          return;
        }
        const seq = Number(e.lastEventId || 0);
        if (seq > 0) lastSeq = Math.max(lastSeq, seq);
        if (ev.kind === "agent_delta") {
          agentBuf += ev.delta;
          scheduleFlush();
          return;
        }
        if (ev.kind === "command_output") {
          const key = typeof ev.item_id === "string" ? ev.item_id : "";
          commandBufs.set(key, (commandBufs.get(key) ?? "") + ev.delta);
          scheduleFlush();
          return;
        }
        // ALWAYS flush pending deltas before a non-delta event
        flushNow();
        dispatch({ type: "event", ev, seq });
      };
      mine.onerror = () => {
        if (mine !== es || disposed || recovering) return;
        if (mine.readyState === EventSource.CLOSED) {
          // a non-2xx reply (400 project not open after a restart, 404 no
          // open project owns the thread after the idle reaper): the
          // browser will NOT retry - the old ladder waited for a second
          // error and stayed on "正在重新连接…" until a manual reload
          if (status !== "reconnecting" && status !== "recovering") setStatus("reconnecting");
          scheduleRecover(1000);
          return;
        }
        if (firstErrorAt === null) {
          firstErrorAt = Date.now();
          setStatus("reconnecting");
        } else if (Date.now() - firstErrorAt > RECOVERY_AFTER_MS) {
          void recover();
        }
      };
    };

    const recover = async (): Promise<void> => {
      if (disposed || recovering) return;
      recovering = true;
      probe(threadId, { recoveries: (window.__cpChannel?.[threadId]?.recoveries ?? 0) + 1 });
      setStatus("recovering");
      // DISCARD the old EventSource - a fresh one starts at the cursor of
      // the new transcript snapshot with no Last-Event-ID header
      es?.close();
      es = null;
      flushNow();
      try {
        if (project) await openProject(project);
        await bootstrap();
        if (disposed) return;
        firstErrorAt = null;
        recovering = false;
        connect();
      } catch {
        recovering = false;
        if (!disposed) {
          setStatus("dead");
          scheduleRecover(RECOVERY_RETRY_MS);
        }
      }
    };

    /** Coming back to the tab / network: is the channel still alive, and
     * does the server hold anything we do not? */
    const reconcile = async (): Promise<void> => {
      if (disposed || recovering) return;
      probe(threadId, { reconciles: (window.__cpChannel?.[threadId]?.reconciles ?? 0) + 1 });
      const silentMs = Date.now() - lastMessageAt;
      if (es === null || es.readyState !== EventSource.OPEN || silentMs > STALE_AFTER_MS) {
        setStatus("reconnecting");
        await recover();
        return;
      }
      try {
        const t = await getTranscript(threadId, project ?? undefined, { limit: 1 });
        if (disposed || recovering) return;
        const gen = t.generation ?? null;
        const cursor = t.live_cursor ?? 0;
        if (gen !== null && generation !== null && gen !== generation) {
          await recover();
          return;
        }
        // events the server has that never reached us (and nothing has
        // arrived in the last two seconds, so this is not just in flight)
        if (cursor > lastSeq && Date.now() - lastMessageAt > 2000) {
          await recover();
        }
      } catch {
        // the server is unreachable: the watchdog / onerror ladder will act
      }
    };

    const start = async (): Promise<void> => {
      setStatus("connecting");
      // idempotent server-side; guarantees the thread channel exists before
      // the EventSource connects (deep links into a not-yet-open project)
      try {
        if (project) await openProject(project);
      } catch {
        // the recovery ladder will retry
      }
      await bootstrap();
      if (!disposed) connect();
    };

    const onVisible = (): void => {
      if (document.visibilityState === "visible") {
        if (raf === 0 && hiddenTimer === undefined && (agentBuf !== "" || commandBufs.size > 0)) scheduleFlush();
        void reconcile();
      }
    };
    const onOnline = (): void => {
      void reconcile();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    const watchdog = window.setInterval(() => {
      if (disposed || recovering) return;
      if (Date.now() - lastMessageAt > STALE_AFTER_MS) void reconcile();
    }, WATCHDOG_MS);

    void start();

    return () => {
      disposed = true;
      es?.close();
      if (raf !== 0) cancelAnimationFrame(raf);
      if (hiddenTimer !== undefined) window.clearTimeout(hiddenTimer);
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      window.clearInterval(watchdog);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, [threadId, project, dispatch]);
}
