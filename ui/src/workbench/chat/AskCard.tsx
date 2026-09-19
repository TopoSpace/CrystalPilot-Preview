/** Question card (round-3 R6): the agent's ```ask fence rendered as a card.
 *
 * Two faces of the same data. `AskCardStatic` sits in the transcript where
 * the agent wrote it (what was known, what is disputed, the one question,
 * the fallback). `ComposerAsk` docks the latest UNANSWERED card above the
 * composer - where the approval card already lives - with the options as
 * buttons; a click sends `[prior] 问题：… 回答：…` (steer while a turn runs,
 * send when idle) and the agent treats it as a user-declared fact to verify
 * against the data. "自己回答" drops the same header into the composer for
 * a free-text answer.
 */
import { useState } from "react";
import { latestOpenAsk, priorReply, type AskBlock } from "../../lib/askCard";
import { zh } from "../../lib/zh";
import { motionScrollBehavior, useMotionPreference } from "../../lib/motion";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useThread } from "../../state/ThreadProvider";

function AskFacts({ ask }: { ask: AskBlock }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
      {ask.settled && (
        <>
          <dt className="text-ink-3">{zh.askSettled}</dt>
          <dd className="text-ink-2">{ask.settled}</dd>
        </>
      )}
      {ask.dispute && (
        <>
          <dt className="text-ink-3">{zh.askDispute}</dt>
          <dd className="text-ink-2">{ask.dispute}</dd>
        </>
      )}
      <dt className="text-ink-3">{zh.askQuestion}</dt>
      <dd className="text-sm font-medium text-ink">{ask.question}</dd>
      {ask.fallback && (
        <>
          <dt className="text-ink-3">{zh.askFallback}</dt>
          <dd className="text-ink-2">{ask.fallback}</dd>
        </>
      )}
    </dl>
  );
}

/** The card as it appears inside the agent's message (passive). */
export function AskCardStatic({ ask }: { ask: AskBlock }) {
  return (
    <div
      className="my-2 rounded-card border border-accent/40 bg-accent/5 px-4 py-3"
      data-testid="ask-card"
    >
      <div className="mb-1 text-2xs font-medium text-accent">{zh.askTitle}</div>
      <AskFacts ask={ask} />
      {ask.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ask.options.map((o) => (
            <span
              key={o}
              className="rounded-pill border border-line bg-bg px-2 py-0.5 text-xs text-ink-2"
            >
              {o}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** The actionable card docked above the composer while a question is open. */
export function ComposerAsk() {
  const { state, send, steer } = useThread();
  const draft = useComposerDraft();
  const motion = useMotionPreference();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState<string | null>(null);

  const open = latestOpenAsk(state.items);
  if (open === null || answered === open.itemId) return null;
  const { ask } = open;

  const reply = async (answer: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const text = priorReply(ask, answer);
    const err = state.turn.active ? await steer(text) : await send(text);
    setBusy(false);
    if (err !== null) {
      setError(err);
      return;
    }
    setAnswered(open.itemId);
  };

  const jumpToCard = () => {
    const cards = document.querySelectorAll('[data-testid="ask-card"]');
    cards[cards.length - 1]?.scrollIntoView({ behavior: motionScrollBehavior(motion.reducedMotion), block: "center" });
  };

  return (
    <div
      className="mx-auto mb-2 w-full max-w-3xl rounded-card border border-accent/40 bg-accent/5 px-4 py-3 shadow-sm"
      data-testid="ask-dock"
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden="true"
          className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent text-2xs font-bold text-white"
        >
          ?
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={jumpToCard}
            className="mb-1 block text-2xs font-medium text-accent hover:underline"
          >
            {zh.askTitle}
          </button>
          <AskFacts ask={ask} />
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {ask.options.map((o) => (
              <button
                key={o}
                type="button"
                disabled={busy}
                onClick={() => void reply(o)}
                className="rounded-pill bg-accent px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                {o}
              </button>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={() => draft.insert(priorReply(ask, ""))}
              className="rounded-pill border border-line px-3 py-1 text-xs text-ink-2 transition-colors hover:bg-raised disabled:opacity-50"
            >
              {zh.askAnswerSelf}
            </button>
          </div>
          <div className="mt-1 text-2xs text-ink-3">{zh.askHint}</div>
          {error !== null && <div className="mt-1 text-2xs text-danger">{error}</div>}
        </div>
      </div>
    </div>
  );
}
