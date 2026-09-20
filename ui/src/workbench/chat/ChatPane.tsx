/** Chat column for one thread: channel banner + message list + the
 * actionable approval card docked above the composer (approval-in-composer;
 * the in-stream card is a passive placeholder) + composer. */
import { useState } from "react";
import { ApiError, restartEngine } from "../../lib/wbApi";
import { t } from "../../lib/i18n";
import { useThread } from "../../state/ThreadProvider";
import { useWorkbench } from "../../state/WorkbenchProvider";
import { Composer } from "../composer/Composer";
import { ComposerAsk } from "./AskCard";
import { ComposerApproval } from "./ComposerApproval";
import { MessageList } from "./MessageList";

function ChannelBanner() {
  const { state } = useThread();
  const s = state.channel;
  if (s === "live" || s === "connecting") return null;
  const text =
    s === "recovering"
      ? t.recovering
      : s === "dead"
        ? t.channelDead
        : t.reconnecting;
  return (
    <div className="flex justify-center px-6 pt-2" data-testid="channel-banner" data-channel={s}>
      <span className="rounded-pill bg-warn/10 px-3 py-1 text-xs text-warn" role="status">
        {text}
      </span>
    </div>
  );
}

/** Loud + actionable: MCP transport died mid-session - every crystallography
 * tool call fails until the engine is rebuilt (r6/D1). */
function McpDownBanner() {
  const { state } = useThread();
  const { projectPath } = useWorkbench();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  if (!state.mcpDown) return null;

  const onRestart = async () => {
    if (projectPath === null || busy) return;
    setBusy(true);
    setNote(null);
    try {
      await restartEngine(projectPath);
      // engine_restarted arrives via the event stream and clears the banner
    } catch (e) {
      setNote(
        e instanceof ApiError && e.status === 409
          ? t.mcpRestartBusy
          : String(e),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-6 mt-2 flex items-center gap-3 rounded-card border border-line bg-surface/50 px-4 py-2.5">
      <span className="min-w-0 flex-1 text-xs text-ink-2">
        {t.mcpDownBanner}
        {note !== null && <span className="ml-2 text-ink-3">{note}</span>}
      </span>
      <button
        type="button"
        onClick={() => void onRestart()}
        disabled={busy || projectPath === null}
        className="shrink-0 rounded-pill bg-raised px-3 py-1 text-xs font-medium text-ink-2 transition-colors hover:bg-raised/70 disabled:opacity-50"
      >
        {busy ? t.mcpRestarting : t.mcpRestart}
      </button>
    </div>
  );
}

export function ChatPane() {
  const { state, send, steer, stop } = useThread();

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="chat-pane" data-channel={state.channel}>
      <ChannelBanner />
      <McpDownBanner />
      <MessageList />
      <div className="shrink-0 px-4 pb-4 sm:px-6 sm:pb-5">
        <ComposerApproval />
        <ComposerAsk />
        <div className="mx-auto w-full max-w-[49rem]">
          <Composer
            onSend={send}
            onSteer={steer}
            onStop={() => void stop()}
            turnActive={state.turn.active}
          />
        </div>
      </div>
    </div>
  );
}
