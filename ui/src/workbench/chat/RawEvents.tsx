/** "原始事件": the lifecycle events the reducer received for one card
 * (started / updated / completed / progress), so a row that ended without a
 * result can be read back to the wire instead of trusted or guessed. */
import type { WbEvent } from "../../lib/wbTypes";
import { t } from "../../lib/i18n";
import { keepFocusOnSummary } from "./detailsFocus";
import { MonoBlock } from "./MonoBlock";

function render(raw: readonly WbEvent[]): string {
  return raw
    .map((ev) => {
      const { ts, ...rest } = ev as WbEvent & Record<string, unknown>;
      const when = typeof ts === "number" && Number.isFinite(ts)
        ? new Date(ts > 1e12 ? ts : ts * 1000).toISOString()
        : String(ts);
      try {
        return `${when}  ${JSON.stringify(rest)}`;
      } catch {
        return `${when}  ${String(ev.kind)}`;
      }
    })
    .join("\n");
}

export function RawEvents({ raw }: { raw: readonly WbEvent[] | undefined }) {
  if (!raw || raw.length === 0) return null;
  return (
    <details onToggle={(event) => keepFocusOnSummary(event.currentTarget)} data-testid="raw-events">
      <summary className="detail-toggle">{t.rawEvents}{t.shell.paren(raw.length)}</summary>
      <MonoBlock text={render(raw)} wrapClassName="mt-2" className="activity-output" />
    </details>
  );
}
