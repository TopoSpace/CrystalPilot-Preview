/** One thread: header (title + running state) above the chat pane. The
 * ThreadProvider lives in WorkbenchLayout (so the right pane shares it);
 * this view just consumes it. */
import { useParams } from "react-router-dom";
import { cx } from "../lib/format";
import { zh } from "../lib/zh";
import { useViewMode, type ViewMode } from "../state/ViewMode";
import { useWorkbench } from "../state/WorkbenchProvider";
import { ChatPane } from "./chat/ChatPane";
import { StatusRail } from "./chat/StatusRail";
import { SubagentDirectory } from "./chat/SubagentDirectory";
import { IconFolder } from "./icons";
import { WorkbenchHeader } from "./WorkbenchHeader";

/** 简洁|详细 segmented pill (P1-6 - exactly two tiers, localStorage). */
function ViewModeToggle() {
  const { mode, setMode } = useViewMode();
  const seg = (m: ViewMode, label: string) => (
    <button
      type="button"
      onClick={() => setMode(m)}
      aria-pressed={mode === m}
      className={cx(
        "rounded-pill px-2 py-0.5 text-2xs transition-colors",
        mode === m
          ? "bg-surface font-medium text-ink shadow-sm"
          : "text-ink-3 hover:text-ink-2",
      )}
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      title={zh.viewModeTitle}
      className="ml-auto flex shrink-0 items-center gap-0.5 rounded-pill bg-raised p-0.5"
    >
      {seg("concise", zh.viewConcise)}
      {seg("verbose", zh.viewVerbose)}
    </div>
  );
}

function ThreadHeader({ threadId }: { threadId: string }) {
  const wb = useWorkbench();
  const meta = wb.threads.find((t) => t.thread_id === threadId);
  const title = meta?.title ?? threadId;

  return (
    <WorkbenchHeader>
      <IconFolder size={15} className="shrink-0 text-ink-3" />
      <h1
        className="min-w-0 truncate text-sm font-medium text-ink"
        title={title}
      >
        {title}
      </h1>
      <ViewModeToggle />
      <SubagentDirectory />
    </WorkbenchHeader>
  );
}

export function ThreadView() {
  const { threadId = "" } = useParams();

  return (
    <>
      <ThreadHeader threadId={threadId} />
      <StatusRail />
      <ChatPane />
    </>
  );
}
