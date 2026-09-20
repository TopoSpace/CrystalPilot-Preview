/** Scrolling transcript: folds ChatItems into their renderers and follows
 * the live tail only while the reader stays near it. The status rail owns
 * the working indicator. Focused process blocks retain their structure.
 * Consecutive MINOR actions (done-ok commands, observe tools, auto/resolved
 * approvals, secondary generics) fold into a single collapsed 运行了 N 条命令
 * digest row - the Codex/Claude Code desktop L1 pattern
 * (workdir/research/desktop-harness-visual-spec.md). */
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import { currentActionText } from "../../lib/currentAction";
import { motionScrollBehavior, useMotionPreference } from "../../lib/motion";
import { deliveryFacts, type DeliveryFacts } from "../../lib/delivery";
import { humanizeTool, isCrystalTool, OBSERVE_TOOLS } from "../../lib/toolCards";
import { finalReplyIds, pendingTurnIds, retainScientificResult } from "../../lib/transcriptPresentation";
import { t } from "../../lib/i18n";
import type {
  ApprovalItem,
  ChatItem,
  ReasoningItem,
} from "../../state/threadReducer";
import { useThread } from "../../state/ThreadProvider";
import { useViewMode } from "../../state/ViewMode";
import { AgentMessage, FinalRepliesContext } from "./AgentMessage";
import { ApprovalCard } from "./ApprovalCard";
import { CommandCard } from "./CommandCard";
import { DeliveryCard } from "./DeliveryCard";
import { GenericRow } from "./GenericRow";
import { commandGlyph, genericGlyph, toolGlyph, type ActivityGlyph } from "../../lib/activityIcons";
import { ActivityIcon } from "./ActivityIcon";
import { ActivitySummary } from "./ActivitySummary";
import { ProcessDetails } from "./ProcessDetails";
import { ReasoningGroup } from "./ReasoningBlock";
import { ToolCard } from "./ToolCard";
import { TurnStatusRow } from "./TurnStatusRow";
import { UserBubble } from "./UserBubble";
import { PlaybackCacheContext, PlaybackReportContext, type PlaybackSnapshot } from "./textPlayback";

export { currentActionText };

function renderItem(item: ChatItem) {
  switch (item.type) {
    case "user":
      return <UserBubble item={item} />;
    case "agent":
      return <AgentMessage item={item} />;
    case "tool":
      return <ToolCard item={item} />;
    case "command":
      return <CommandCard item={item} />;
    case "approval":
      return <ApprovalRow item={item} />;
    case "turn":
      return <TurnStatusRow item={item} />;
    case "generic":
      return <GenericRow item={item} />;
    default:
      return null;
  }
}

export function isResolvedApproval(item: ChatItem): boolean {
  return (
    item.type === "approval" &&
    (item.status === "auto" ||
      item.status === "accepted" ||
      item.status === "resolved")
  );
}

/** Auto-approved / accepted approvals duplicate the tool row that follows
 * them ("已批准 调用工具 X" above every card, 2026-09-05 visual review);
 * 简洁 hides them, 详细 shows them. */
function ApprovalRow({ item }: { item: ApprovalItem }) {
  const { verbose } = useViewMode();
  if (!verbose && isResolvedApproval(item)) return null;
  return <ApprovalCard item={item} />;
}

export type Block =
  | { kind: "item"; item: ChatItem }
  | { kind: "reasoning"; items: ReasoningItem[]; id: string }
  | { kind: "actions"; items: ChatItem[]; id: string }
  | { kind: "work"; blocks: WorkChildBlock[]; id: string }
  /** R6: a completed turn's whole process, one fold */
  | { kind: "turnfold"; blocks: Block[]; id: string; counts: FoldCounts }
  /** R6: delivery summary from the product directory, before the divider */
  | { kind: "delivery"; id: string; facts: DeliveryFacts };

export interface FoldCounts {
  tools: number;
  thinks: number;
  commands: number;
  approvals: number;
  subagents: number;
  ms: number;
}

export type WorkChildBlock = Extract<
  Block,
  { kind: "reasoning" } | { kind: "actions" } | { kind: "item" }
>;

/** Presentation only: don't leave blank spacing for approvals hidden in
 * concise mode. The source transcript and paging identities stay intact. */
function visibleBlock(block: Block, verbose: boolean): boolean {
  if (verbose || block.kind === "delivery") return true;
  return blockItems(block).some(item => !isResolvedApproval(item));
}

function spacingKind(block: Block): "activity" | "message" | "user" | "divider" | "delivery" {
  if (block.kind === "delivery") return "delivery";
  if (block.kind !== "item") return "activity";
  if (block.item.type === "user") return "user";
  if (block.item.type === "agent") return "message";
  if (block.item.type === "turn" || (block.item.type === "generic" && block.item.family === "system")) return "divider";
  return "activity";
}

/** A homogeneous digest keeps the action's glyph; mixed work gets a list. */
function digestGlyph(items: ChatItem[]): ActivityGlyph {
  const kinds = new Set(items.filter(it => !isResolvedApproval(it)).map(it => {
    if (it.type === "tool") return toolGlyph(it.tool, isCrystalTool(it));
    if (it.type === "command") return commandGlyph(it.command);
    if (it.type === "generic") return genericGlyph(it.family);
    return "group" as const;
  }));
  return kinds.size === 1 ? [...kinds][0] : "group";
}

/** A minor action folds into a collapsed group; anything running, failed,
 * refused, pending, or milestone-grade (domain tool cards with metric
 * chips) stays a standalone block. */
export function isMinor(item: ChatItem): boolean {
  switch (item.type) {
    case "command":
      return (
        item.done &&
        item.status === "completed" &&
        (item.exitCode === null || item.exitCode === 0)
      );
    case "tool": {
      if (retainScientificResult(item)) return false;
      if (item.status !== "ok" || !OBSERVE_TOOLS.has(item.tool)) return false;
      // a warning observation (twin alarm, validation alerts) must not be
      // buried inside a collapsed group
      const tone = humanizeTool(item).tone;
      return tone !== "warn" && tone !== "danger";
    }
    case "approval":
      return (
        item.status === "auto" ||
        item.status === "accepted" ||
        item.status === "resolved"
      );
    case "generic":
      return (
        item.done &&
        item.phase !== "interrupted" &&
        item.phase !== "no_result" &&
        item.family !== "system" &&
        item.family !== "error" &&
        item.family !== "client_error"
      );
    default:
      return false;
  }
}

/** Fold consecutive reasoning items into single blocks and consecutive
 * minor actions into digest groups (>=2); drop turn-started markers (the
 * status rail + completed divider carry that state). */
export function toBlocks(items: ChatItem[]): Block[] {
  const blocks: Block[] = [];
  for (const item of items) {
    if (item.type === "turn" && item.phase === "started") continue;
    if (item.type === "reasoning") {
      const last = blocks.at(-1);
      if (last && last.kind === "reasoning") {
        last.items.push(item);
        continue;
      }
      blocks.push({ kind: "reasoning", items: [item], id: item.id });
      continue;
    }
    if (isMinor(item)) {
      const last = blocks.at(-1);
      if (last && last.kind === "actions") {
        last.items.push(item);
        continue;
      }
      blocks.push({ kind: "actions", items: [item], id: item.id });
      continue;
    }
    blocks.push({ kind: "item", item });
  }
  // singleton "groups" render as the plain item row
  return blocks.map((b) =>
    b.kind === "actions" && b.items.length === 1
      ? { kind: "item" as const, item: b.items[0] }
      : b,
  );
}

/** Wave-2 turn collapse (Codex "Worked for Xs"): a contiguous run of >= 2
 * reasoning/actions blocks - the grunt work between prose paragraphs -
 * folds into ONE 已工作 row. While the turn is live the tail run stays
 * open so live rows stay visible; it refolds on completion unless focused.
 * Milestone cards, failures and prose are never inside a fold. */
export function foldWorkRuns(blocks: Block[], turnActive: boolean): Block[] {
  const out: Block[] = [];
  let run: WorkChildBlock[] = [];
  const flush = (isTail: boolean) => {
    if (run.length === 0) return;
    if (run.length === 1 || (isTail && turnActive)) out.push(...run);
    else {
      const head = run[0];
      const id = head.kind === "item" ? head.item.id : head.id;
      out.push({ kind: "work", blocks: run, id });
    }
    run = [];
  };
  for (const b of blocks) {
    // singleton minors were demoted to plain items by toBlocks; they are
    // still grunt work (想→跑一条命令→再想 is the common shape) and must
    // not break a run
    if (
      b.kind === "reasoning" ||
      b.kind === "actions" ||
      (b.kind === "item" && isMinor(b.item))
    ) {
      run.push(b);
    } else {
      flush(false);
      out.push(b);
    }
  }
  flush(true);
  return out;
}

/** Items a fold must never swallow: scientific results, prose, failures, pending approvals,
 * system rows and the turn dividers themselves stay in the open. */
function isLoud(item: ChatItem): boolean {
  switch (item.type) {
    case "agent":
      // Narrative remains the spine of the conversation, including commentary.
      return true;
    case "tool": {
      const tone = humanizeTool(item).tone;
      return retainScientificResult(item) || item.status !== "ok" || tone === "warn" || tone === "danger";
    }
    case "command":
      return !isMinor(item);
    case "approval":
      return (
        item.status === "pending" ||
        item.status === "rejected" ||
        item.status === "timeout"
      );
    case "generic":
      return (
        !item.done ||
        item.phase === "interrupted" ||
        item.phase === "no_result" ||
        item.family === "system" ||
        item.family === "error" ||
        item.family === "client_error"
      );
    case "turn":
    case "user":
      return true;
    default:
      return false;
  }
}

function blockItems(b: Block): ChatItem[] {
  switch (b.kind) {
    case "item":
      return [b.item];
    case "reasoning":
    case "actions":
      return b.items;
    case "work":
      return b.blocks.flatMap(blockItems);
    case "turnfold":
      return b.blocks.flatMap(blockItems);
    default:
      return [];
  }
}

function blockIsLoud(b: Block): boolean {
  return blockItems(b).some(isLoud);
}

export function foldCounts(blocks: Block[]): FoldCounts {
  const c: FoldCounts = {
    tools: 0,
    thinks: 0,
    commands: 0,
    approvals: 0,
    subagents: 0,
    ms: 0,
  };
  let tsMin = Infinity;
  let tsMax = -Infinity;
  const countReasoning = (b: Block) => {
    if (b.kind === "reasoning") c.thinks += 1;
    else if (b.kind === "work") b.blocks.forEach(countReasoning);
    else if (b.kind === "turnfold") b.blocks.forEach(countReasoning);
  };
  for (const b of blocks) {
    countReasoning(b);
    for (const it of blockItems(b)) {
      if (it.type === "tool") c.tools += 1;
      else if (it.type === "command") c.commands += 1;
      else if (it.type === "approval") c.approvals += 1;
      else if (
        it.type === "generic" &&
        it.family === "collab" &&
        it.kind === "collab_completed"
      )
        c.subagents += 1;
      if (it.ts < tsMin) tsMin = it.ts;
      if (it.ts > tsMax) tsMax = it.ts;
    }
  }
  c.ms = spanMs(tsMin, tsMax);
  return c;
}

/** Event timestamps are seconds from the server (Date.now()/1000 for
 * optimistic rows); anything that looks like milliseconds is taken as such.
 * The result is always milliseconds - the forensic replay of the 2026-09-05
 * demo showed a 2904 s segment labelled "00:03" because the raw second
 * difference was fed to a millisecond formatter. */
export function spanMs(tsMin: number, tsMax: number): number {
  const span = tsMax - tsMin;
  if (!Number.isFinite(span) || span <= 0) return 0;
  return tsMax > 1e12 ? span : span * 1000;
}

export function foldLabel(
  c: FoldCounts,
  opts: { approvals?: boolean } = {},
): string {
  const parts: string[] = [];
  if (c.tools > 0) parts.push(`${c.tools} ${t.foldTools}`);
  if (c.thinks > 0) parts.push(`${c.thinks} ${t.foldThinks}`);
  if (c.commands > 0) parts.push(`${c.commands} ${t.foldCommands}`);
  // resolved approvals are hidden in 简洁 (they duplicate the tool rows),
  // so their count is only meaningful in 详细
  if (c.approvals > 0 && opts.approvals)
    parts.push(`${c.approvals} ${t.foldApprovals}`);
  if (c.subagents > 0) parts.push(`${c.subagents} ${t.foldSubagents}`);
  return parts.join(" · ");
}

/** Completed-turn fold (R6, DeepSeek "turn process folding"): between a
 * user message and the turn divider that closes it, everything that is
 * auxiliary process - reasoning, navigation tools, commands and resolved
 * approvals - folds by contiguous run. Scientific results and narrative stay out;
 * the final reply (the trailing agent prose) stays out, and so does
 * anything loud (failures, refusals, pending approvals, system rows). A
 * delivery card is inserted before the divider when the turn wrote the
 * product. The live turn (no divider yet) is untouched. */
export function foldCompletedTurns(blocks: Block[]): Block[] {
  const out: Block[] = [];
  let seg: Block[] = [];
  let inSeg = false;
  const flushSeg = (divider: Block | null) => {
    if (!inSeg) {
      out.push(...seg);
      seg = [];
      return;
    }
    // trailing agent prose = the final reply
    let tail = seg.length;
    while (tail > 0) {
      const b = seg[tail - 1];
      if (b.kind === "item" && b.item.type === "agent") tail -= 1;
      else break;
    }
    const body = seg.slice(0, tail);
    const reply = seg.slice(tail);
    // Each maximal run of quiet blocks between loud ones becomes its own
    // fold, so a fold never crosses a loud row and the displayed order is
    // the event order (the single-fold form moved later quiet work in
    // front of an earlier failure - forensics 2026-09-05, 4 inversions).
    let run: Block[] = [];
    const flushRun = () => {
      if (run.length >= 2) {
        const head = run[0];
        const id = head.kind === "item" ? head.item.id : head.id;
        out.push({
          kind: "turnfold",
          blocks: run,
          id: `fold-${id}`,
          counts: foldCounts(run),
        });
      } else {
        out.push(...run);
      }
      run = [];
    };
    for (const b of body) {
      if (blockIsLoud(b)) {
        flushRun();
        out.push(b);
      } else {
        run.push(b);
      }
    }
    flushRun();
    out.push(...reply);
    if (
      divider !== null &&
      divider.kind === "item" &&
      divider.item.type === "turn"
    ) {
      const delivered = seg
        .flatMap(blockItems)
        .filter(
          (it): it is Extract<ChatItem, { type: "tool" }> =>
            it.type === "tool" &&
            it.status === "ok" &&
            (it.tool === "write_outputs" || it.tool === "finalize_delivery"),
        );
      if (delivered.length > 0) {
        // the LAST successful call of each wins (a rejected finalize is
        // filtered out above: status ok only)
        const fin = [...delivered]
          .reverse()
          .find((d) => d.tool === "finalize_delivery");
        const wrote = [...delivered]
          .reverse()
          .find((d) => d.tool === "write_outputs");
        out.push({
          kind: "delivery",
          id: `deliv-${divider.item.id}`,
          facts: deliveryFacts(wrote?.summary?.parsed, fin?.summary?.parsed),
        });
      }
    }
    seg = [];
    inSeg = false;
  };
  for (const b of blocks) {
    // A steer (插话) lands INSIDE the running turn: it is loud (never
    // folded) but not a segment boundary - treating it as one folded the
    // live turn's work mid-flight (160 -> 32 blocks, forensics 2026-09-05).
    if (b.kind === "item" && b.item.type === "user" && !b.item.steer) {
      flushSeg(null);
      out.push(b);
      inSeg = true;
      continue;
    }
    if (b.kind === "item" && b.item.type === "turn") {
      flushSeg(b);
      out.push(b);
      continue;
    }
    seg.push(b);
  }
  // an open segment is the live turn (or an interrupted one): untouched
  out.push(...seg);
  return out;
}

/** "运行了 5 条命令 · 3 次检视" - counts by kind, approvals uncounted
 * (they accompany the commands they approved; still listed inside). */
export function digestLabel(items: ChatItem[]): string {
  let nCmd = 0;
  let nObs = 0;
  let nOther = 0;
  for (const it of items) {
    if (it.type === "command") nCmd += 1;
    else if (it.type === "tool") nObs += 1;
    else if (it.type === "generic") nOther += 1;
  }
  const parts: string[] = [];
  if (nCmd > 0) parts.push(`${nCmd} ${t.digestCommands}`);
  if (nObs > 0) parts.push(`${nObs} ${t.digestObserves}`);
  if (nOther > 0) parts.push(`${nOther} ${t.digestOthers}`);
  if (parts.length === 0) parts.push(`${items.length} ${t.digestOthers}`);
  return `${t.digestPrefix}${parts.join(" · ")}`;
}

function WorkGroup({ blocks }: { blocks: WorkChildBlock[] }) {
  const { verbose } = useViewMode();
  const label = foldLabel(foldCounts(blocks), { approvals: verbose });
  return (
    <ProcessDetails className="activity-row activity-group">
      <ActivitySummary icon={<ActivityIcon kind="group" />}>{t.workedFor}{label ? ` · ${label}` : ""}</ActivitySummary>
      <div className="activity-body activity-group-body">
        {blocks.filter(b => visibleBlock(b, verbose)).map((b) =>
          b.kind === "reasoning" ? (
            <ReasoningGroup key={blockKey(b)} items={b.items} />
          ) : b.kind === "actions" ? (
            <ActionGroup key={blockKey(b)} items={b.items} />
          ) : (
            <div key={blockKey(b)}>{renderItem(b.item)}</div>
          ),
        )}
      </div>
    </ProcessDetails>
  );
}

function TurnFold({ blocks, counts }: { blocks: Block[]; counts: FoldCounts }) {
  const { verbose } = useViewMode();
  return (
    <ProcessDetails className="activity-row activity-group" data-testid="turn-fold">
      <ActivitySummary icon={<ActivityIcon kind="group" />}>{t.turnFoldPrefix} · {foldLabel(counts, { approvals: verbose })}</ActivitySummary>
      <div className="activity-body activity-group-body">
        {blocks.filter(b => visibleBlock(b, verbose)).map((b) => (
          <div key={blockKey(b)}>
            {renderBlock(b)}
          </div>
        ))}
      </div>
    </ProcessDetails>
  );
}

/** The product files as the artifacts poll sees them on disk - the only
 * source a delivery summary may trust (never the prose). */
function renderBlock(block: Block) {
  switch (block.kind) {
    case "reasoning":
      return <ReasoningGroup items={block.items} />;
    case "actions":
      return <ActionGroup items={block.items} />;
    case "work":
      return <WorkGroup blocks={block.blocks} />;
    case "turnfold":
      return <TurnFold blocks={block.blocks} counts={block.counts} />;
    case "delivery":
      return <DeliveryCard facts={block.facts} />;
    default:
      return renderItem(block.item);
  }
}

function ActionGroup({ items }: { items: ChatItem[] }) {
  const { verbose } = useViewMode(); // P1-6
  const visible = verbose
    ? items
    : items.filter((it) => !isResolvedApproval(it));
  if (visible.length === 0) return null;
  return (
    <ProcessDetails className="activity-row activity-group">
      <ActivitySummary icon={<ActivityIcon kind={digestGlyph(visible)} />}>{digestLabel(visible)}</ActivitySummary>
      <div className="activity-body activity-group-body">
        {visible.map((it) => (
          <div key={itemSource(it)}>{renderItem(it)}</div>
        ))}
      </div>
    </ProcessDetails>
  );
}

const STICK_THRESHOLD_PX = 160;
// thousand-item campaign transcripts: render only the newest window and
// let the user page older content in - the DOM cost of 2000+ rows is the
// last big janker after memoization (blocks are post-folding, so one
// "block" may already summarize dozens of actions)
const RENDER_WINDOW_BLOCKS = 300;
const RENDER_WINDOW_STEP = 300;

function itemSource(item: ChatItem): string {
  if (item.eid !== undefined) return `${item.type}:eid:${item.eid}`;
  if (item.type === "command" && item.itemId) return `command:${item.itemId}`;
  if (item.type === "approval") return `approval:${item.approvalId}`;
  // Legacy transcripts lack eids. Ambiguous timestamp matches cannot be held.
  return JSON.stringify([item.type, item.ts, item.type === "tool" ? [item.server, item.tool] : null]);
}

function blockKey(block: Block): string {
  if (block.kind === "item" && block.item.type === "agent" && block.item.renderId) return block.item.renderId;
  if (block.kind === "item") return `item:${itemSource(block.item)}`;
  const first = blockItems(block)[0];
  return first ? `${block.kind}:${itemSource(first)}` : block.id;
}

function blockAnchor(block: Block): string {
  const first = blockItems(block)[0];
  return first ? itemSource(first) : blockKey(block);
}

/** Keep the focused block's DOM shape across stream/turn boundaries, while
 * refreshing only the same persisted sources. Prepend renumbers local ids. */
export function projectBlocks(items: ChatItem[], active: boolean, focused: Block | null = null): Block[] {
  const fold = (rows: ChatItem[]) => foldCompletedTurns(foldWorkRuns(toBlocks(rows), active));
  if (!focused) return fold(items);
  const bySource = new Map<string, { item: ChatItem; index: number } | null>();
  items.forEach((item, index) => {
    const source = itemSource(item);
    bySource.set(source, bySource.has(source) ? null : { item, index });
  });
  const heldItems = blockItems(focused);
  if (heldItems.length === 0) return fold(items);
  const positions: number[] = [];
  for (const held of heldItems) {
    const match = bySource.get(itemSource(held));
    if (!match || match.item.type !== held.type) return fold(items);
    positions.push(match.index);
  }
  // A missing, inserted or reordered row must not disappear inside the pin.
  if (positions.some((index, i) => index !== positions[0] + i)) return fold(items);
  const current = (item: ChatItem) => bySource.get(itemSource(item))?.item;
  const refresh = (block: Block): Block | null => {
    switch (block.kind) {
      case "item": {
        const item = current(block.item);
        return item?.type === block.item.type ? { ...block, item } : null;
      }
      case "reasoning": {
        const reasoning: ReasoningItem[] = [];
        for (const old of block.items) {
          const item = current(old);
          if (item?.type !== "reasoning") return null;
          reasoning.push(item);
        }
        return { ...block, id: reasoning[0].id, items: reasoning };
      }
      case "actions": {
        const actions: ChatItem[] = [];
        for (const old of block.items) {
          const item = current(old);
          if (!item || !isMinor(item)) return null;
          actions.push(item);
        }
        return { ...block, id: actions[0].id, items: actions };
      }
      case "work": {
        const children: WorkChildBlock[] = [];
        for (const child of block.blocks) {
          const next = refresh(child);
          if (!next || (next.kind !== "item" && next.kind !== "reasoning" && next.kind !== "actions") || blockIsLoud(next)) return null;
          children.push(next);
        }
        return { ...block, blocks: children };
      }
      case "turnfold": {
        const children: Block[] = [];
        for (const child of block.blocks) {
          const next = refresh(child);
          if (!next || blockIsLoud(next)) return null;
          children.push(next);
        }
        return { ...block, blocks: children, counts: foldCounts(children) };
      }
      default: return block;
    }
  };
  const held = refresh(focused);
  if (!held) return fold(items);
  return [...fold(items.slice(0, positions[0])), held, ...fold(items.slice(positions.at(-1)! + 1))];
}

export function MessageList() {
  const { state, loadEarlier } = useThread();
  const { verbose } = useViewMode();
  const motion = useMotionPreference();
  const [focusedBlock, setFocusedBlock] = useState<Block | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const playbackCache = useRef(new Map<string, PlaybackSnapshot>());
  const [playbackStatus, setPlaybackStatus] = useState(new Map<string, boolean>());
  const reportPlayback = useCallback((id: string, pending: boolean) => {
    setPlaybackStatus(previous => previous.get(id) === pending ? previous : new Map(previous).set(id, pending));
  }, []);
  const waitingTurns = useMemo(() => pendingTurnIds(state.items, playbackStatus), [state.items, playbackStatus]);
  const stickRef = useRef(true);
  const readingStartKeyRef = useRef<string | null>(null);

  const itemCount = state.items.length;
  const lastItem = state.items.at(-1);
  const finalReplies = useMemo(() => finalReplyIds(state.items), [state.items]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current && motion.pageVisible && !el.contains(document.activeElement)) {
      el.scrollTop = el.scrollHeight;
    }
  }, [itemCount, lastItem, motion.pageVisible]);

  // Playback grows locally even while the network is silent. Follow those
  // layout changes only while the reader has chosen to stay at the tail.
  useLayoutEffect(() => {
    const column = columnRef.current;
    if (!column) return;
    const observer = new ResizeObserver(() => {
      const el = scrollRef.current;
      if (el && stickRef.current && motion.pageVisible && !el.contains(document.activeElement)) el.scrollTop = el.scrollHeight;
    });
    observer.observe(column);
    return () => observer.disconnect();
  }, [motion.pageVisible]);

  // "回到最新" appears only once the reader has scrolled up (Codex /
  // Claude Code); sticking is restored by the click, never by new rows
  const [atBottom, setAtBottom] = useState(true);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const near =
      el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
    stickRef.current = near;
    if (near) readingStartKeyRef.current = null;
    else if (readingStartKeyRef.current === null) {
      readingStartKeyRef.current = el.querySelector<HTMLElement>("[data-chat-block]")?.dataset.chatBlock ?? null;
    }
    setAtBottom(near);
  };
  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = true;
    readingStartKeyRef.current = null;
    setAtBottom(true);
    el.scrollTo({ top: el.scrollHeight, behavior: motionScrollBehavior(motion.reducedMotion) });
  };

  // items is replaced on every reducer patch, so this memo re-runs exactly
  // when the transcript actually changed - not on unrelated re-renders
  const allBlocks = useMemo(
    () => projectBlocks(state.items, state.turn.active, focusedBlock),
    [state.items, state.turn.active, focusedBlock],
  );
  const [extraShown, setExtraShown] = useState(0);
  const windowSize = RENDER_WINDOW_BLOCKS + extraShown;
  const focusIndex = focusedBlock ? allBlocks.findIndex((b) => blockKey(b) === blockKey(focusedBlock)) : -1;
  const readingIndex = readingStartKeyRef.current === null ? -1
    : allBlocks.findIndex((b) => blockKey(b) === readingStartKeyRef.current);
  const hiddenCount = Math.min(
    Math.max(0, allBlocks.length - windowSize),
    focusIndex >= 0 ? focusIndex : Infinity,
    readingIndex >= 0 ? readingIndex : Infinity,
  );
  const blocks = hiddenCount > 0 ? allBlocks.slice(hiddenCount) : allBlocks;
  // What the user typed never leaves the DOM (DeepSeek rule; forensics F-4:
  // the 300-block window pushed the one interjection of a 3-hour session
  // out of the page after a reload). The process around those inputs stays
  // behind "显示更早"; the inputs themselves are shown above it.
  const hiddenUserBlocks = useMemo(
    () =>
      hiddenCount > 0
        ? allBlocks
            .slice(0, hiddenCount)
            .filter((b) => b.kind === "item" && b.item.type === "user")
        : [],
    [allBlocks, hiddenCount],
  );
  // keep the viewport anchored when older content is prepended - both when
  // the in-memory window widens and when an older transcript page lands
  const anchorRef = useRef<{ distance: number; key?: string; offset?: number } | null>(null);
  const rememberAnchor = () => {
    const el = scrollRef.current;
    if (!el) return;
    const top = el.getBoundingClientRect().top;
    const row = [...el.querySelectorAll<HTMLElement>("[data-chat-block]")]
      .find((node) => node.getBoundingClientRect().bottom > top);
    anchorRef.current = {
      distance: el.scrollHeight - el.scrollTop,
      key: row?.dataset.chatAnchor,
      offset: row ? row.getBoundingClientRect().top - top : undefined,
    };
    stickRef.current = false;
  };
  const showEarlier = () => {
    rememberAnchor();
    setExtraShown((n) => n + RENDER_WINDOW_STEP);
  };
  const loadEarlierPage = () => {
    rememberAnchor();
    stickRef.current = false;
    void loadEarlier();
  };
  const oldestEid = state.page.oldestEid;
  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const el = scrollRef.current;
    if (el) {
      const row = [...el.querySelectorAll<HTMLElement>("[data-chat-block]")]
        .find((node) => node.dataset.chatAnchor === anchor.key);
      if (row && anchor.offset !== undefined) {
        el.scrollTop += row.getBoundingClientRect().top - el.getBoundingClientRect().top - anchor.offset;
      } else {
        el.scrollTop = el.scrollHeight - anchor.distance;
      }
      readingStartKeyRef.current = el.querySelector<HTMLElement>("[data-chat-block]")?.dataset.chatBlock ?? null;
    }
    anchorRef.current = null;
  }, [extraShown, oldestEid]);
  // older lines still on the server, beyond what any window can show
  const remainingOnServer =
    state.page.hasMore && oldestEid !== null ? Math.max(0, oldestEid - 1) : 0;

  return (
    <FinalRepliesContext.Provider value={finalReplies}>
    <PlaybackCacheContext.Provider value={playbackCache.current}>
    <PlaybackReportContext.Provider value={reportPlayback}>
    <div
      ref={scrollRef}
      data-testid="message-scroll"
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div ref={columnRef} className="transcript-column mx-auto flex w-full flex-col px-6 py-6">
        {state.items.length === 0 && state.channel !== "connecting" && (
          <div className="py-16 text-center text-sm text-ink-3">
            {t.emptyThread}
          </div>
        )}
        {state.channel === "connecting" && state.items.length === 0 && (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-3">
            {t.loading}
          </div>
        )}
        {hiddenUserBlocks.length > 0 && (
          <div
            className="flex flex-col gap-2 opacity-80"
            data-testid="earlier-inputs"
          >
            <div className="text-center text-2xs text-ink-3">
              {t.earlierInputs}
            </div>
            {hiddenUserBlocks.map((block) => (
              <div key={blockKey(block)}>
                {renderBlock(block)}
              </div>
            ))}
          </div>
        )}
        {hiddenCount > 0 ? (
          <button
            type="button"
            onClick={showEarlier}
            className="mx-auto h-7 rounded-pill border border-line px-3 text-xs text-ink-3 transition-colors hover:bg-raised hover:text-ink"
          >
            {t.showEarlierPrefix}
            {Math.min(hiddenCount, RENDER_WINDOW_STEP)}
            {t.showEarlierSuffix}
          </button>
        ) : remainingOnServer > 0 ? (
          <button
            type="button"
            onClick={loadEarlierPage}
            disabled={state.page.loading}
            data-testid="load-earlier"
            className="mx-auto h-7 rounded-pill border border-line px-3 text-xs text-ink-3 transition-colors hover:bg-raised hover:text-ink disabled:opacity-60"
          >
            {state.page.loading
              ? t.showEarlierLoading
              : `${t.showEarlierServer} · ${t.showEarlierRemainingPrefix}${remainingOnServer}${t.showEarlierRemainingSuffix}`}
          </button>
        ) : null}
        {blocks.filter(block => visibleBlock(block, verbose) && !(block.kind === "item" && block.item.type === "turn" && waitingTurns.has(block.item.id))).map((block) => (
          <div
            key={blockKey(block)}
            data-chat-block={blockKey(block)}
            data-chat-anchor={blockAnchor(block)}
            data-chat-kind={spacingKind(block)}
            onFocusCapture={() => setFocusedBlock((held) => held && blockKey(held) === blockKey(block) ? held : block)}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setFocusedBlock(null);
            }}
          >
            {renderBlock(block)}
          </div>
        ))}
      </div>
      {!atBottom && (
        <div className="pointer-events-none sticky bottom-3 z-20 flex justify-center">
          <button
            type="button"
            onClick={jumpToLatest}
            data-testid="jump-to-latest"
            className="row-in pointer-events-auto inline-flex h-7 items-center gap-1 rounded-pill border border-line bg-bg/95 px-3 text-xs text-ink-2 shadow-sm backdrop-blur-sm transition-colors hover:bg-raised hover:text-ink"
          >
            ↓ {t.jumpToLatest}
          </button>
        </div>
      )}
    </div>
    </PlaybackReportContext.Provider>
    </PlaybackCacheContext.Provider>
    </FinalRepliesContext.Provider>
  );
}
