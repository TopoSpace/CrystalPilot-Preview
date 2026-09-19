/** Codex-style reasoning summary (思考摘要): consecutive reasoning items
 * collapse into one quiet block whose header previews the latest summary.
 * Expanding shows every summary in order; activity stays on the status rail. */
import { useState } from "react";
import { cx } from "../../lib/format";
import { zh } from "../../lib/zh";
import type { ReasoningItem } from "../../state/threadReducer";
import { IconChevronDown, IconSpark } from "../icons";

/** Strip markdown emphasis/heading noise for the one-line preview. */
function previewOf(text: unknown): string {
  // a malformed reasoning payload (null / non-string text) must degrade to
  // an empty preview, not take the whole tree down (forensics 2026-09-05:
  // an unguarded .replace on null blanked #root)
  if (typeof text !== "string") return "";
  return text
    .replace(/[*_#`]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

export function ReasoningGroup({ items }: { items: ReasoningItem[] }) {
  const [open, setOpen] = useState(false);
  const latest = items.at(-1);
  if (!latest) return null;
  const preview = previewOf(latest.text);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="activity-summary group"
      >
        <IconSpark size={17} className="shrink-0" />
        <span className="activity-copy">
        <span className="shrink-0">{zh.reasoningSummary}</span>
        {items.length > 1 && (
          <span className="shrink-0 text-ink-3 tabular-nums">
            ×{items.length}
          </span>
        )}
        {!open && (
          <span className="truncate pl-1 text-ink-3">
            {preview}
          </span>
        )}
        <IconChevronDown size={13} className={cx("activity-chevron", open && "rotate-180 !opacity-75")} />
        </span>
      </button>
      {open && (
        <div className="mt-1.5 flex flex-col gap-2 border-l-2 border-line pl-3">
          {items.map((it) => (
            <div
              key={it.id}
              className="text-sm leading-relaxed whitespace-pre-wrap text-ink-2"
            >
              {it.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Single-item wrapper kept for API compatibility with older callers. */
export function ReasoningBlock({ item }: { item: ReasoningItem }) {
  return <ReasoningGroup items={[item]} />;
}
