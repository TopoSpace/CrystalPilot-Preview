import { cx } from "../../lib/format";
import {
  humanizeTool,
  isCrystalTool,
  type ToolChipSpec,
  type ToolHumanized,
} from "../../lib/toolCards";
import { t } from "../../lib/i18n";
import { ProcessDetails } from "./ProcessDetails";
import type { ToolCardItem } from "../../state/threadReducer";
import { toolGlyph } from "../../lib/activityIcons";
import { ActivityIcon } from "./ActivityIcon";
import { ActivitySummary } from "./ActivitySummary";
import { keepFocusOnSummary } from "./detailsFocus";
import { MonoBlock } from "./MonoBlock";
import { RawEvents } from "./RawEvents";

function rawDetails(item: ToolCardItem): string {
  const parts: string[] = [];
  parts.push(`tool: ${item.tool}`);
  if (item.args !== undefined && item.args !== null) {
    try {
      parts.push(`args: ${JSON.stringify(item.args, null, 2)}`);
    } catch {
      /* unserializable */
    }
  }
  if (item.summary?.parsed !== undefined) {
    try {
      parts.push(`result: ${JSON.stringify(item.summary.parsed, null, 2)}`);
    } catch {
      /* unserializable */
    }
  } else if (item.resultTail) {
    parts.push(`result_tail: ${item.resultTail}`);
  }
  if (item.error) parts.push(`error: ${item.error}`);
  return parts.join("\n\n");
}

const chipToneCls: Record<
  NonNullable<ToolChipSpec["tone"]> | "neutral",
  string
> = {
  neutral: "bg-raised/70 text-ink-2",
  ok: "bg-ok/10 text-ok",
  warn: "bg-warn/10 text-warn",
  danger: "bg-raised/70 text-ink-2",
};

function ChipRow({ chips }: { chips: ToolChipSpec[] }) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((c, i) => (
        <span
          key={i}
          className={cx(
            "inline-flex h-[20px] items-center rounded-md px-1.5 font-mono text-2xs tabular-nums",
            chipToneCls[c.tone ?? "neutral"],
          )}
        >
          {c.text}
        </span>
      ))}
    </div>
  );
}

/** The one-line result: the metric chips as text (first four), or the
 * caveat, or nothing. Failures put their reason here. */
export function resultSentence(
  h: ToolHumanized,
  status: ToolCardItem["status"],
): string {
  if (status === "running") return "";
  if (status === "error" || status === "interrupted" || status === "no_result") return h.warn ?? "";
  const bits = h.chips.slice(0, 4).map((c) => c.text);
  if (bits.length > 0)
    return bits.join(" · ") + (h.chips.length > 4 ? " …" : "");
  return h.warn ?? "";
}

/** Scientific results stay readable in the transcript; raw data stays on demand. */
export function ToolCard({ item }: { item: ToolCardItem }) {
  const h = humanizeTool(item);
  const running = item.status === "running";
  const scientific = isCrystalTool(item);
  const issue = item.status === "error" ? t.toolFailed
    : item.status === "interrupted" ? t.toolInterrupted
      : item.status === "no_result" ? t.toolNoResult : undefined;
  const boundaryHint = item.status === "no_result" ? t.toolNoResultHint
    : item.status === "interrupted" ? t.toolInterruptedHint : null;
  const sentence = resultSentence(h, item.status);
  const hasBody = h.chips.length > 0 || h.warn !== null || h.body !== null || h.detail !== null;

  return (
    <ProcessDetails
      data-testid="tool-row"
      data-status={item.status}
      data-scientific={scientific ? "true" : "false"}
      data-tool={item.tool}
      running={running}
      className="activity-row row-in"
    >
      <ActivitySummary
        icon={<ActivityIcon kind={toolGlyph(item.tool, scientific)} scientific={scientific} />}
        running={running}
        issue={issue}
        title={item.tool + (sentence ? ` · ${sentence}` : "")}
      >
        <span className={scientific ? "activity-title scientific-title" : "activity-title"}>{h.title}</span>
        {!running && sentence && <span className="activity-result"> · {sentence}</span>}
      </ActivitySummary>
      <span className="sr-only">{running ? t.toolRunning : issue ?? t.toolDone}</span>
      <div className="activity-body">
        {item.server && item.server !== "crystalpilot" && <div className="text-xs text-ink-3">{item.server}</div>}
        {running && item.progressLine && <div className="text-sm text-ink-2">{item.progressLine}</div>}
        {boundaryHint !== null && (
          <div className="text-sm leading-relaxed text-ink-2" data-testid="tool-boundary-hint">{boundaryHint}</div>
        )}
        {h.warn !== null && boundaryHint === null && <div className="text-sm leading-relaxed text-ink-2">{h.warn}</div>}
        <ChipRow chips={h.chips} />
        {h.body !== null && <div className="text-sm leading-relaxed text-ink-2">{h.body}</div>}
        {h.detail !== null && <div className="text-sm leading-relaxed text-ink-2">{h.detail}</div>}
        {hasBody ? (
          <details onToggle={(event) => keepFocusOnSummary(event.currentTarget)}>
            <summary className="detail-toggle">{t.technicalDetails}</summary>
            <MonoBlock text={rawDetails(item)} wrapClassName="mt-2" className="activity-output" />
          </details>
        ) : <MonoBlock text={rawDetails(item)} className="activity-output" />}
        <RawEvents raw={item.raw} />
      </div>
    </ProcessDetails>
  );
}
