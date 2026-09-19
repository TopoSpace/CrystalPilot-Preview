/** Per-thread state: reducer + SSE channel + send/steer/stop/decide actions.
 *
 * Send/steer race handling: send gets 409 while a turn is running -> fall
 * back to steer; steer gets 409 when idle -> fall back to send. The user
 * message itself arrives back over SSE and reconciles the optimistic bubble.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { setDiagnosticContext } from "../lib/diagnostics";
import {
  ApiError,
  decideApproval,
  getArtifacts,
  getCommandOutput,
  getTranscript,
  interruptThread,
  sendMessage,
  steerThread,
} from "../lib/wbApi";
import type { ApprovalDecisionChoice, AttachmentRef } from "../lib/wbTypes";
import {
  initialThreadState,
  threadReducer,
  type ThreadState,
} from "./threadReducer";
import { useThreadChannel } from "./useThreadChannel";

export interface ThreadContextValue {
  state: ThreadState;
  project: string | null;
  send: (
    text: string,
    attachments?: AttachmentRef[],
  ) => Promise<string | null>;
  steer: (
    text: string,
    attachments?: AttachmentRef[],
  ) => Promise<string | null>;
  stop: () => Promise<void>;
  decide: (
    approvalId: string,
    decision: ApprovalDecisionChoice,
  ) => Promise<string | null>;
  /** fetch the transcript page before the oldest loaded event */
  loadEarlier: () => Promise<void>;
  /** full stored output of a shell command, by codex item id */
  commandOutput: (itemId: string) => Promise<string>;
  /** client-local card in the transcript (slash command output) */
  note: (title: string, lines: string[]) => void;
}

const PAGE_SIZE = 2000;

const ARTIFACTS_POLL_MS = 9000;
const ARTIFACTS_RETRY_MS = 4000;

const ThreadContext = createContext<ThreadContextValue | null>(null);

export function useThread(): ThreadContextValue {
  const ctx = useContext(ThreadContext);
  if (ctx === null) {
    throw new Error("useThread must be used inside ThreadProvider");
  }
  return ctx;
}

/** Null-safe variant for components that render both inside and outside a
 * thread route (right pane, composer chrome). */
export function useThreadOptional(): ThreadContextValue | null {
  return useContext(ThreadContext);
}

let optimisticCounter = 0;

export function ThreadProvider({
  threadId,
  project,
  children,
}: {
  threadId: string;
  project: string | null;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(
    threadReducer,
    threadId,
    initialThreadState,
  );
  useThreadChannel(threadId, project, dispatch);

  // Artifacts: fetch on mount and whenever the turn settles (covers the
  // bootstrap path - `idle` events are live-only). Early requests can 404:
  // during a running turn REPORT.json / final.cif are not written yet, and on
  // bootstrap the fetch can race the project session opening. So instead of
  // giving up after one failure: poll every ~9 s while the turn is active
  // (stops on settle - active -> false re-runs this effect for a final pull),
  // and when idle retry a failed fetch a few times with a short delay.
  const active = state.turn.active;
  const channelReady = state.channel === "live";
  useEffect(() => {
    // The channel opens only after project/thread registration; fetching
    // artifacts sooner races that registration on a cold deep link.
    if (!channelReady) return undefined;
    let cancelled = false;
    let retryTimer: number | null = null;
    let idleRetriesLeft = 4;
    const pull = () => {
      void getArtifacts(threadId)
        .then((artifacts) => {
          if (!cancelled) dispatch({ type: "artifacts", artifacts });
        })
        .catch(() => {
          // active: the interval below retries; idle: bounded catch-up
          if (cancelled || active || idleRetriesLeft <= 0) return;
          idleRetriesLeft -= 1;
          retryTimer = window.setTimeout(pull, ARTIFACTS_RETRY_MS);
        });
    };
    pull();
    const interval = active
      ? window.setInterval(pull, ARTIFACTS_POLL_MS)
      : null;
    return () => {
      cancelled = true;
      if (interval !== null) window.clearInterval(interval);
      if (retryTimer !== null) window.clearTimeout(retryTimer);
    };
  }, [threadId, active, channelReady]);

  const projectRef = useRef(project);
  projectRef.current = project;
  const stateRef = useRef(state);
  stateRef.current = state;

  // what an ErrorBoundary / window.onerror report will carry
  const lastKind = state.rawEvents.at(-1)?.kind ?? null;
  useEffect(() => {
    setDiagnosticContext({
      threadId,
      project,
      cursor: state.cursor,
      itemCount: state.items.length,
      lastEventKind: lastKind,
    });
  }, [threadId, project, state.cursor, state.items.length, lastKind]);

  const loadEarlier = useCallback(async () => {
    const { page } = stateRef.current;
    if (!page.hasMore || page.loading || page.oldestEid === null) return;
    dispatch({ type: "page_loading", loading: true });
    try {
      const t = await getTranscript(threadId, projectRef.current ?? undefined, {
        before: page.oldestEid,
        limit: PAGE_SIZE,
      });
      dispatch({
        type: "prepend",
        events: t.events,
        page: {
          total: t.total ?? null,
          oldestEid: t.oldest_eid ?? page.oldestEid,
          hasMore: t.has_more === true,
        },
      });
    } catch {
      dispatch({ type: "page_loading", loading: false });
    }
  }, [threadId]);

  const commandOutput = useCallback(
    (itemId: string) =>
      getCommandOutput(threadId, itemId, projectRef.current ?? undefined),
    [threadId],
  );

  const send = useCallback(
    async (
      text: string,
      attachments?: AttachmentRef[],
    ): Promise<string | null> => {
      const proj = projectRef.current;
      if (!proj) return "没有打开的项目";
      optimisticCounter += 1;
      dispatch({
        type: "optimistic_user",
        id: `opt${optimisticCounter}`,
        text,
        steer: false,
        attachments: attachments?.map((a) => a.name ?? a.rel),
      });
      try {
        await sendMessage({
          project: proj,
          message: text,
          thread_id: threadId,
          attachments,
        });
        return null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          // a turn is running -> steer instead
          try {
            await steerThread(threadId, text, attachments);
            return null;
          } catch (e2) {
            return e2 instanceof Error ? e2.message : String(e2);
          }
        }
        return e instanceof Error ? e.message : String(e);
      }
    },
    [threadId],
  );

  const steer = useCallback(
    async (
      text: string,
      attachments?: AttachmentRef[],
    ): Promise<string | null> => {
      optimisticCounter += 1;
      dispatch({
        type: "optimistic_user",
        id: `opt${optimisticCounter}`,
        text,
        steer: true,
        attachments: attachments?.map((a) => a.name ?? a.rel),
      });
      try {
        await steerThread(threadId, text, attachments);
        return null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          // thread idle -> plain send
          const proj = projectRef.current;
          if (!proj) return "没有打开的项目";
          try {
            await sendMessage({
              project: proj,
              message: text,
              thread_id: threadId,
              attachments,
            });
            return null;
          } catch (e2) {
            return e2 instanceof Error ? e2.message : String(e2);
          }
        }
        return e instanceof Error ? e.message : String(e);
      }
    },
    [threadId],
  );

  const stop = useCallback(async () => {
    try {
      await interruptThread(threadId);
    } catch {
      /* already idle */
    }
  }, [threadId]);

  const decide = useCallback(
    async (
      approvalId: string,
      decision: ApprovalDecisionChoice,
    ): Promise<string | null> => {
      try {
        await decideApproval(approvalId, decision);
        // optimistic resolve; the SSE approval_decision echo is idempotent
        dispatch({
          type: "event",
          ev: {
            kind: "approval_decision",
            approval_id: approvalId,
            method: "",
            decision,
            ts: Date.now() / 1000,
          },
          seq: 0,
        });
        return null;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        // backend no longer knows this approval (auto-decided or timed out
        // while the SSE echo was missed): the CARD is stale, not the click
        // wrong - resolve it locally instead of erroring (r11 case-c)
        if (/no such pending approval/i.test(msg)) {
          dispatch({ type: "approval_gone", approvalId });
          return null;
        }
        return msg;
      }
    },
    [],
  );

  const note = useCallback((title: string, lines: string[]) => {
    dispatch({
      type: "event",
      ev: { kind: "note", title, lines, ts: Date.now() / 1000 },
      seq: 0,
    });
  }, []);

  const value = useMemo<ThreadContextValue>(
    () => ({ state, project, send, steer, stop, decide, loadEarlier, commandOutput, note }),
    [state, project, send, steer, stop, decide, loadEarlier, commandOutput, note],
  );

  return (
    <ThreadContext.Provider value={value}>{children}</ThreadContext.Provider>
  );
}
