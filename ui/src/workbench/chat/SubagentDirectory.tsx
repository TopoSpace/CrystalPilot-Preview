/** "/ N 子代理" trigger in the thread header (R6): the delegated agents of
 * this thread from collab_* events - status, duration, model / effort,
 * the spawn prompt. Renders nothing when the thread never delegated. */
import { clickedOutside } from "../../lib/outsideClick";
import { useEffect, useRef, useState } from "react";
import { cx } from "../../lib/format";
import { t } from "../../lib/i18n";
import { useThread } from "../../state/ThreadProvider";
import { fmtMmSs } from "./TurnStatusRow";

function toMs(ts: number): number {
  return ts > 1e12 ? ts : ts * 1000;
}

export function SubagentDirectory() {
  const { state } = useThread();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (clickedOutside(ref.current, e)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const subs = state.subagents;
  if (subs.length === 0) return null;
  const live = subs.filter((s) => s.endedTs === null && !/completed|done|closed|failed|error/i.test(s.status)).length;
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cx(
          "flex h-6 items-center gap-1 rounded-pill px-2 text-2xs transition-colors",
          live > 0 ? "bg-accent-fill/15 text-accent" : "text-ink-3 hover:bg-raised hover:text-ink",
        )}
        title={t.subagentsTrigger}
      >
        / {subs.length} {t.subagentsTrigger}
      </button>
      {open && (
        <div className="absolute top-full right-0 z-30 mt-1 w-[26rem] max-w-[90vw] rounded-card border border-line bg-bg p-2 shadow-lg">
          <ul className="max-h-72 overflow-y-auto">
            {subs.map((s) => {
              const dur = s.endedTs !== null ? toMs(s.endedTs) - toMs(s.startedTs) : null;
              return (
                <li key={s.id} className="border-b border-line/60 px-1 py-1.5 last:border-b-0">
                  <div className="flex items-baseline gap-2 text-xs">
                    <span className="font-mono text-2xs text-ink-3">{s.id.slice(0, 12)}</span>
                    <span className="rounded-pill bg-raised px-1.5 text-2xs text-ink-2">{s.status}</span>
                    {dur !== null && (
                      <span className="font-mono text-2xs text-ink-3 tabular-nums">{fmtMmSs(dur)}</span>
                    )}
                    {(s.model || s.effort) && (
                      <span className="ml-auto font-mono text-2xs text-ink-3">
                        {[s.model, s.effort].filter(Boolean).join(" · ")}
                      </span>
                    )}
                  </div>
                  {s.prompt && (
                    <div className="mt-0.5 line-clamp-3 text-2xs text-ink-2" title={s.prompt}>
                      {t.subagentPrompt}{t.shell.colon}{s.prompt}
                    </div>
                  )}
                  {s.message && <div className="mt-0.5 text-2xs text-ink-3">{s.message}</div>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
