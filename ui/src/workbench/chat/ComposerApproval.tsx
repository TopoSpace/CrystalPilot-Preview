/** Approval-in-composer (DeepSeek Harness pattern): while approvals are
 * pending, the actionable card sits directly above the composer - where
 * the user's attention and hands already are - instead of somewhere up
 * the stream. The in-stream ApprovalCard stays as a passive placeholder.
 *
 * Handles one approval at a time (oldest first); a queue chip shows how
 * many are waiting behind it. Params fold out on demand.
 */
import { useState } from "react";
import { zh } from "../../lib/zh";
import { motionScrollBehavior, useMotionPreference } from "../../lib/motion";
import type { ApprovalItem } from "../../state/threadReducer";
import { useThread } from "../../state/ThreadProvider";
import { IconChevronRight, IconShield } from "../icons";
import { approvalFacets, describeApproval } from "./ApprovalCard";

export function ComposerApproval() {
  const { state, decide } = useThread();
  const motion = useMotionPreference();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showParams, setShowParams] = useState(false);

  const pending = state.items.filter(
    (it): it is ApprovalItem =>
      it.type === "approval" && it.status === "pending",
  );
  if (pending.length === 0) return null;
  const item = pending[0];
  const { message, params } = describeApproval(item);
  const facets = approvalFacets(item);

  const onDecide = async (
    decision: "accept" | "reject" | "accept_for_session",
  ) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const err = await decide(item.approvalId, decision);
    setBusy(false);
    setShowParams(false);
    if (err !== null) setError(err);
  };

  const jumpToContext = () => {
    document
      .getElementById(`approval-${item.approvalId}`)
      ?.scrollIntoView({ behavior: motionScrollBehavior(motion.reducedMotion), block: "center" });
  };

  return (
    <div className="mx-auto mb-2 w-full max-w-3xl rounded-card border border-warn/40 bg-warn/5 px-4 py-3 shadow-sm">
      <div className="flex items-start gap-2.5">
        <IconShield size={15} className="mt-0.5 shrink-0 text-warn" />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={jumpToContext}
            title={zh.approvalJump}
            className="block w-full truncate text-left text-sm font-medium text-ink hover:underline"
          >
            {message}
          </button>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-2xs">
            {facets.why && (
              <>
                <dt className="text-ink-3">{zh.approvalWhy}</dt>
                <dd className="text-ink-2">{facets.why}</dd>
              </>
            )}
            <dt className="text-ink-3">{zh.approvalRisk}</dt>
            <dd className="text-ink-2">{facets.risk}</dd>
            {facets.files.length > 0 && (
              <>
                <dt className="text-ink-3">{zh.approvalFiles}</dt>
                <dd className="truncate font-mono text-ink-2" title={facets.files.join("\n")}>
                  {facets.files.join(" · ")}
                </dd>
              </>
            )}
          </dl>
          {params.length > 0 && (
            <button
              type="button"
              onClick={() => setShowParams((v) => !v)}
              className="mt-1 flex items-center gap-1 text-2xs text-ink-3 transition-colors hover:text-ink"
            >
              <IconChevronRight
                size={11}
                className={showParams ? "rotate-90 transition-transform" : "transition-transform"}
              />
              {zh.approvalShowParams} ({params.length})
            </button>
          )}
          {showParams && (
            <div className="mt-1 flex max-h-40 flex-col gap-0.5 overflow-y-auto">
              {params.map((p) => (
                <div key={p.name} className="flex gap-2 font-mono text-xs">
                  <span className="shrink-0 text-ink-3">{p.name}</span>
                  <span className="break-all text-ink-2">{p.value}</span>
                </div>
              ))}
            </div>
          )}
          {error !== null && (
            <div className="mt-1 text-xs text-danger">{error}</div>
          )}
        </div>
        {pending.length > 1 && (
          <span className="mt-0.5 shrink-0 rounded-pill bg-warn/10 px-2 py-0.5 text-2xs tabular-nums text-warn">
            {zh.approvalQueuePrefix} {pending.length}
          </span>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2 pl-[25px]">
        <button
          type="button"
          disabled={busy}
          onClick={() => void onDecide("accept")}
          className="h-7 rounded-lg bg-ink px-3 text-xs font-medium text-bg transition-opacity hover:opacity-85 disabled:opacity-40"
        >
          {zh.approve}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onDecide("reject")}
          className="h-7 rounded-lg border border-line bg-bg px-3 text-xs font-medium text-ink transition-colors hover:bg-raised disabled:opacity-40"
        >
          {zh.reject}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onDecide("accept_for_session")}
          className="h-7 rounded-lg px-2 text-xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
        >
          {zh.approveForSession}
        </button>
      </div>
    </div>
  );
}
