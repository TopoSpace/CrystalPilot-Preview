/** Thin muted divider marking a turn's end: 已完成 {mm:ss} / 已中断 / 失败,
 * plus a one-line turn digest (nodes committed, R1 movement, top tools).
 * turn-started markers render nothing; the status rail carries activity. */
import { fmtMmSs } from "../../lib/format";
import { zh } from "../../lib/zh";
import type { TurnAggregate, TurnStatusItem } from "../../state/threadReducer";
import { useViewMode } from "../../state/ViewMode";

/** De-JSON a provider/transport failure into one human sentence (P1-9).
 * Digs message-ish fields out of JSON blobs, translates the common
 * signatures, truncates; the raw text stays on the row's title attr. */
export function humanTurnError(raw: string): string {
  let msg = raw.trim();
  // dig into JSON error envelopes, innermost message wins
  for (let depth = 0; depth < 4; depth++) {
    const start = msg.indexOf("{");
    if (start === -1) break;
    try {
      const obj: unknown = JSON.parse(msg.slice(start));
      if (!obj || typeof obj !== "object") break;
      const o = obj as Record<string, unknown>;
      const next = [o.error, o.detail, o.message]
        .map((v) =>
          typeof v === "string"
            ? v
            : v && typeof v === "object"
              ? JSON.stringify(v)
              : null,
        )
        .find((v): v is string => v !== null && v !== "");
      if (!next || next === msg) break;
      msg = next.trim();
    } catch {
      break;
    }
  }
  const low = msg.toLowerCase();
  if (low.includes("timeout") || low.includes("timed out")) {
    return `${zh.turnErrTimeout}（${msg.slice(0, 120)}）`;
  }
  if (low.includes("429") || low.includes("rate limit")) {
    return zh.turnErrRateLimit;
  }
  if (/\b5\d\d\b/.test(low) || low.includes("internal server")) {
    return `${zh.turnErrUpstream}（${msg.slice(0, 120)}）`;
  }
  return msg.length > 200 ? `${msg.slice(0, 200)}…` : msg;
}

export { fmtMmSs };

export function TurnStatusRow({ item }: { item: TurnStatusItem }) {
  if (item.phase === "started") return null;

  let text: string;
  let cls = "text-ink-3";
  if (item.phase === "failed") {
    text = `! ${zh.turnFailed}${
      item.error ? `：${humanTurnError(item.error)}` : ""
    }`;
    cls = "text-ink-2";
  } else if (item.status === "interrupted") {
    text = zh.turnInterrupted;
    cls = "text-ink-2";
  } else if (item.status === "failed") {
    text = `! ${zh.turnFailed}`;
    cls = "text-ink-2";
  } else {
    const d = fmtMmSs(item.durationMs);
    text = d ? `${zh.turnDone} · ${d}` : zh.turnDone;
  }

  return (
    <div className="flex flex-col gap-1" id={`turn-${item.id}`} data-testid="turn-status" data-status={item.status}>
      <div className={`flex items-center gap-2 text-2xs ${cls}`}>
        <span className="h-px w-4 bg-line" />
        <span
          className="tabular-nums"
          title={
            item.phase === "failed" ? (item.error ?? undefined) : undefined
          }
        >
          {text}
        </span>
        <span className="h-px flex-1 bg-line" />
      </div>
      {item.summary && <TurnDigest agg={item.summary} />}
    </div>
  );
}

/** The digest as one line of text (the stage track lists turns by it). */
export function turnDigestText(agg: TurnAggregate): string {
  const bits: string[] = [];
  if (agg.nodes.length === 1) {
    bits.push(`${zh.digestNodes} ${agg.nodes[0]}`);
  } else if (agg.nodes.length > 1) {
    bits.push(
      `${zh.digestNodes} ${agg.nodes[0]}…${agg.nodes[agg.nodes.length - 1]}（${agg.nodes.length}）`,
    );
  }
  if (
    agg.r1From !== null &&
    agg.r1To !== null &&
    Math.abs(agg.r1From - agg.r1To) >= 0.00005
  ) {
    bits.push(`R1 ${agg.r1From.toFixed(4)}→${agg.r1To.toFixed(4)}`);
  } else if (agg.r1To !== null) {
    bits.push(`R1 ${agg.r1To.toFixed(4)}`);
  }
  const topTools = agg.tools
    .slice(0, 4)
    .map(([name, n]) => (n > 1 ? `${name}×${n}` : name));
  if (topTools.length > 0) {
    const extra = agg.tools.length > 4 ? " …" : "";
    bits.push(topTools.join(" ") + extra);
  }
  if (agg.nCommands > 0) bits.push(`shell×${agg.nCommands}`);
  return bits.join(" · ");
}

function TurnDigest({ agg }: { agg: TurnAggregate }) {
  const { verbose } = useViewMode();
  const text = turnDigestText(verbose ? agg : { ...agg, tools: [], nCommands: 0 });
  if (text === "") return null;
  return (
    <div className="truncate pl-6 font-mono text-2xs text-ink-3 tabular-nums">
      {text}
    </div>
  );
}
