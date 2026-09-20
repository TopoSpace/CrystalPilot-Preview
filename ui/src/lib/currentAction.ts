/** "What is the agent doing right now" as one humanized line (Devin
 * "Follow" / Manus narration minimal form, spec P1-5). Backwards scan: the
 * newest live marker wins within the current turn. The status rail is the
 * single working indicator; history never supplies a new turn's action. */
import type { ReactNode } from "react";
import type { ChatItem } from "../state/threadReducer";
import { runningJobLine, runningJobs, type BackgroundJobInfo } from "./backgroundJobs";
import { humanizeCommand } from "./humanizeCommand";
import { humanizeTool } from "./toolCards";
import { t } from "./i18n";

export function currentActionText(
  items: ChatItem[],
  liveToolIds?: readonly string[],
  backgroundJobs?: Readonly<Record<string, BackgroundJobInfo>>,
  nowMs?: number,
): ReactNode {
  const primary = primaryAction(items, liveToolIds);
  // a detached solver (SHELXT in its silent space-group search) is the
  // most important thing happening even while the agent sleeps or polls:
  // it rides after the live tool, or stands alone when there is none
  const bg = backgroundJobs ? runningJobs(backgroundJobs) : [];
  if (bg.length > 0) {
    const line = runningJobLine(bg[bg.length - 1], nowMs);
    if (primary === null || primary === undefined) return line;
    // a rich (non-string) title cannot be joined in a .ts file: it keeps
    // the line; the job is still on its own system row
    return typeof primary === "string" ? `${primary} · ${line}` : primary;
  }
  return primary ?? t.stickyThinking;
}

function primaryAction(
  items: ChatItem[],
  liveToolIds?: readonly string[],
): ReactNode | null {
  const liveTools = liveToolIds === undefined ? null : new Set(liveToolIds);
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.type === "turn") break;
    if (it.type === "approval" && it.status === "pending") {
      return t.stickyApproval;
    }
    if (
      it.type === "tool" &&
      it.status === "running" &&
      (liveTools === null || liveTools.has(it.id))
    ) {
      // the tool's own progress line (tool_progress: "等待 SHELXL 作业 · 42 s")
      // is the most specific thing we know, so it rides after the title
      const title = humanizeTool(it).title;
      return it.progressLine ? `${title} · ${it.progressLine}` : title;
    }
    if (it.type === "command" && !it.done) {
      return humanizeCommand(it.command).label;
    }
    if (it.type === "generic" && !it.done) {
      if (it.family === "file_change") return t.stickyEditingFile;
      if (it.family === "webSearch") return t.stickySearching;
    }
  }
  return null;
}
