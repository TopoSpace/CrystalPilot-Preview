import type { ChatItem, ToolCardItem } from "../state/threadReducer";
import { isCrystalTool } from "./toolCards";

// Navigation and instruction lookups do not change a scientific judgment.
// Unknown CrystalPilot tools stay visible until explicitly classified here.
const AUXILIARY_TOOLS = new Set([
  "list_nodes", "list_skills", "read_skill", "save_skill",
  "delete_skill", "view_structure",
]);

export function retainScientificResult(item: ToolCardItem): boolean {
  return isCrystalTool(item) && !AUXILIARY_TOOLS.has(item.tool);
}

/** A completed message event can still be commentary. Only the final prose
 * of a successfully completed turn gets the assistant copy action. */
export function finalReplyIds(items: ChatItem[]): ReadonlySet<string> {
  const ids = new Set<string>();
  let candidate: Extract<ChatItem, { type: "agent" }> | null = null;
  for (const item of items) {
    if (item.type === "agent") candidate = item.streaming ? null : item;
    else if (item.type === "tool" || item.type === "command" || item.type === "reasoning") candidate = null;
    else if (item.type === "user" && !item.steer) candidate = null;
    else if (item.type === "turn") {
      if (item.phase === "completed" && item.status === "completed" && candidate) ids.add(candidate.id);
      candidate = null;
    }
  }
  return ids;
}

/** A successful divider waits for every message in that turn, including
 * the last fade. Unreported live rows are pending until their first commit;
 * historical rows have no renderId and need no playback. */
export function pendingTurnIds(items: ChatItem[], playback: ReadonlyMap<string, boolean>): ReadonlySet<string> {
  const pending = new Set<string>();
  let waiting = false;
  for (const item of items) {
    if (item.type === "user" && !item.steer) waiting = false;
    if (item.type === "agent") waiting ||= item.streaming || (item.renderId !== undefined && playback.get(item.renderId) !== false);
    if (item.type === "turn") {
      if (item.phase === "completed" && item.status === "completed" && waiting) pending.add(item.id);
      waiting = false;
    }
  }
  return pending;
}
