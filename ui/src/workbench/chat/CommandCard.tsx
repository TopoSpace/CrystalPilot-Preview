import { useState } from "react";
import { humanizeCommand } from "../../lib/humanizeCommand";
import { t } from "../../lib/i18n";
import { useThreadOptional } from "../../state/ThreadProvider";
import { ProcessDetails } from "./ProcessDetails";
import type { CommandCardItem } from "../../state/threadReducer";
import { commandGlyph } from "../../lib/activityIcons";
import { ActivityIcon } from "./ActivityIcon";
import { MonoBlock } from "./MonoBlock";
import { ActivitySummary } from "./ActivitySummary";
import { RawEvents } from "./RawEvents";

/** The transcript keeps a 1500-char tail of a command's output; when the
 * server stored more, offer it on demand (forensics F-6). */
function FullOutput({ item }: { item: CommandCardItem }) {
  const thread = useThreadOptional();
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (
    thread === null ||
    item.itemId === null ||
    item.outputLen === null ||
    item.outputLen <= item.output.length
  ) {
    return null;
  }
  if (text !== null) {
    return (
      <MonoBlock
        text={text.trimEnd()}
        className="activity-output"
      />
    );
  }
  const fetchFull = () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    thread
      .commandOutput(item.itemId as string)
      .then((t) => setText(t))
      .catch(() => setError(t.commandFullOutputMissing))
      .finally(() => setBusy(false));
  };
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={fetchFull}
        disabled={busy}
        data-testid="command-full-output"
        className="h-6 rounded-pill border border-line px-2.5 text-2xs text-ink-3 transition-colors hover:bg-raised hover:text-ink disabled:opacity-60"
      >
        {busy
          ? t.loading
          : `${t.commandFullOutput}${t.shell.paren(`${item.outputLen.toLocaleString()} ${t.commandFullOutputChars}`)}`}
      </button>
      {error !== null && <span className="text-2xs text-ink-2">{error}</span>}
    </div>
  );
}

/** L3 detail: unwrapped command, raw host command line, full output. */
function DetailBlocks({ item }: { item: CommandCardItem }) {
  const h = humanizeCommand(item.command);
  return (
    <div className="mt-1.5 flex flex-col gap-1.5">
      <MonoBlock
        text={h.inner}
        className="activity-output"
      />
      {h.inner !== item.command && (
        <details>
          <summary className="cursor-pointer list-none text-2xs text-ink-3 select-none hover:text-ink-2">
            {t.rawCommand}
          </summary>
          <MonoBlock
            text={item.command}
            wrapClassName="mt-1"
            className="overflow-x-auto rounded-lg bg-raised/40 p-2.5 font-mono text-2xs leading-relaxed whitespace-pre-wrap text-ink-3"
          />
        </details>
      )}
      {item.output !== "" && (
        <MonoBlock
          text={item.output.trimEnd()}
          className="activity-output"
        />
      )}
      <FullOutput item={item} />
    </div>
  );
}

export function CommandCard({ item }: { item: CommandCardItem }) {
  const running = !item.done;
  const failed = item.done && (item.status === "failed" || (item.exitCode !== null && item.exitCode !== 0));
  const noResult = item.done && !failed && item.status === "no_result";
  const interrupted = item.done && !failed && !noResult && item.status !== "completed";
  const h = humanizeCommand(item.command);
  const issue = failed ? (item.exitCode === null ? t.toolFailed : `${t.exitCode} ${item.exitCode}`)
    : noResult ? t.toolNoResult : interrupted ? t.toolInterrupted : undefined;
  const dataStatus = running ? "running" : failed ? "failed" : noResult ? "no_result" : interrupted ? "interrupted" : "completed";
  return (
    <ProcessDetails className="activity-row row-in" running={running}
      data-testid="command-row" data-status={dataStatus}>
      <ActivitySummary icon={<ActivityIcon kind={commandGlyph(item.command)} />} running={running} issue={issue} title={item.command}>
        {running ? t.shell.commandRunning(h.label) : noResult ? `${t.toolNoResult} · ${h.label}` : interrupted ? `${t.turnInterrupted} · ${h.label}` : failed ? `${t.toolInterrupted} · ${h.label}` : t.shell.commandDone(h.label)}
      </ActivitySummary>
      <div className="activity-body">
        {issue && <div className="text-sm text-ink-2">{issue}</div>}
        {noResult && <div className="text-sm leading-relaxed text-ink-2" data-testid="tool-boundary-hint">{t.toolNoResultHint}</div>}
        {interrupted && <div className="text-sm leading-relaxed text-ink-2" data-testid="tool-boundary-hint">{t.toolInterruptedHint}</div>}
        <DetailBlocks item={item} />
        <RawEvents raw={item.raw} />
      </div>
    </ProcessDetails>
  );
}
