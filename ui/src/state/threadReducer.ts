/** Pure reducer that folds the workbench event stream into chat items.
 *
 * Wire quirks handled here (verified against real transcripts):
 * - statuses may arrive as stringified Python enums ("TurnStatus.completed");
 * - tool events carry NO call id AND tools run in parallel (real transcripts
 *   show 3 tool_started before the first tool_completed) - pairing is FIFO by
 *   (server, tool) name among open cards; orphan completions append a card;
 * - agent_delta / command_output / token_usage / idle are live-only (never in
 *   the transcript), so stream deltas are gated on turn.active to keep an SSE
 *   replay of a finished turn from opening ghost streaming items;
 * - transcript/live boundary dedup: exact (kind,ts) match against the
 *   transcript tail, plus user_message text match within 3 s.
 */
import { safeParseResultTail, type ResultSummary } from "../lib/resultTail";
import {
  normalizeEnum,
  type ArtifactEntry,
  type TokenCounts,
  type WbEvent,
} from "../lib/wbTypes";
import {
  jobInfoFromEvent,
  jobNameFromArg,
  type BackgroundJobInfo,
} from "../lib/backgroundJobs";

// ------------------------------------------------------------------- items

export interface UserItem {
  type: "user";
  id: string;
  ts: number;
  text: string;
  steer: boolean;
  pending: boolean;
  /** display names of files sent with the message */
  attachments?: string[];
  /** transcript identity once persisted (round-3 R1) */
  eid?: number;
  /** round-3 R6 steer receipt: did the words reach the model? absent =
   * persisted, not (yet) confirmed either way */
  receipt?: "submitted" | "failed";
  receiptError?: string;
}

export interface AgentItem {
  type: "agent";
  id: string;
  ts: number;
  text: string;
  streaming: boolean;
  /** Client-only identity: a live reply keeps its playback when it gains an eid. */
  renderId?: string;
}

export interface ReasoningItem {
  type: "reasoning";
  id: string;
  ts: number;
  text: string;
}

/** Last-seen model metrics, advanced by state-changing tool completions.
 * Stamped onto tool cards as `metricsBefore` so humanizers can render deltas
 * (e.g. R1 0.1036 → 0.0618). */
export interface MetricsSnapshot {
  r1?: number;
  wr2?: number;
  goof?: number;
  diffMapMax?: number;
  nParams?: number;
}

export interface ToolCardItem {
  type: "tool";
  id: string;
  ts: number;
  server: string | null;
  tool: string;
  args: unknown;
  /** Display lifecycle derived from the wire. `interrupted` = the turn was
   * stopped or failed while this ran; `no_result` = the turn ended normally
   * (or the transcript was cut) and no completion event for this call was
   * ever received. Neither is success or failure. */
  status: "running" | "ok" | "error" | "interrupted" | "no_result";
  rawStatus: string;
  durationMs: number | null;
  ok: boolean | null;
  resultTail: string | null;
  error: string | null;
  progressLine: string | null;
  summary: ResultSummary | null;
  /** Metrics cursor value at completion time (null while running / no data). */
  metricsBefore: MetricsSnapshot | null;
  /** codex item id (null on transcripts written before 2026-09-16) */
  itemId: string | null;
  /** the lifecycle events received for this call, oldest first (bounded) */
  raw: WbEvent[];
}

export interface CommandCardItem {
  type: "command";
  id: string;
  ts: number;
  command: string;
  /** wire status, or "interrupted" / "no_result" when closed by a turn boundary */
  status: string;
  exitCode: number | null;
  output: string;
  done: boolean;
  /** codex item id (null on old transcripts) - key for the full output */
  itemId: string | null;
  /** total output length reported at completion; null when unknown */
  outputLen: number | null;
  outputFile: string | null;
  /** the lifecycle events received for this command, oldest first (bounded) */
  raw: WbEvent[];
}

export type ApprovalStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "timeout"
  | "auto"
  /** backend resolved it while the SSE echo was missed; outcome unknown */
  | "resolved";

export interface ApprovalItem {
  type: "approval";
  id: string;
  ts: number;
  approvalId: string;
  method: string;
  detail: unknown;
  mcpServer: string | null;
  mcpMessage: string | null;
  mcpToolParams: unknown;
  status: ApprovalStatus;
}

/** Per-turn digest shown under the end-of-turn divider: what ran, which
 * nodes were committed, how the headline metric moved. */
export interface TurnAggregate {
  /** [tool name, call count], most-used first */
  tools: [string, number][];
  /** committed node ids in commit order */
  nodes: string[];
  nCommands: number;
  r1From: number | null;
  r1To: number | null;
}

export interface TurnStatusItem {
  type: "turn";
  id: string;
  ts: number;
  phase: "started" | "completed" | "failed";
  status: string | null;
  durationMs: number | null;
  error: string | null;
  summary?: TurnAggregate;
}

export interface GenericItem {
  type: "generic";
  id: string;
  ts: number;
  kind: string;
  /** e.g. "file_change" for file_change_started - used to fold phases. */
  family: string;
  phase: string;
  detail: unknown;
  done: boolean;
  /** codex item id when the wire carried one (pairs phases of one item) */
  itemId?: string | null;
}

export type ChatItem = (
  | UserItem
  | AgentItem
  | ReasoningItem
  | ToolCardItem
  | CommandCardItem
  | ApprovalItem
  | TurnStatusItem
  | GenericItem
) & { /** Persistent source event, unlike the reducer-local `id`. */ eid?: number };

// ------------------------------------------------------------------- state

export type ChannelStatus =
  "connecting" | "live" | "reconnecting" | "recovering" | "dead";

export interface TurnState {
  active: boolean;
  taskId: string | null;
  startedTs: number | null;
  endStatus: string | null;
  durationMs: number | null;
}

export interface UsageState {
  last: TokenCounts | null;
  total: TokenCounts | null;
  contextWindow: number | null;
}

export interface CrystalSignal {
  seq: number;
  tool: string;
  node?: string;
}

/** One delegated agent as seen through collab_* events: the receiver thread
 * id is its identity; the spawn prompt is its job description. */
export interface SubagentEntry {
  id: string;
  prompt: string | null;
  model: string | null;
  effort: string | null;
  status: string;
  startedTs: number;
  endedTs: number | null;
  /** last agents_states message for this receiver */
  message: string | null;
}

export interface ThreadState {
  threadId: string;
  /** subagents spawned in this thread (R6 子代理目录), spawn order */
  subagents: SubagentEntry[];
  channel: ChannelStatus;
  items: ChatItem[];
  itemIndex: Record<string, number>;
  openAgentId: string | null;
  /** Most recently started still-running tool card (tool_progress target). */
  openToolId: string | null;
  /** All still-running tool cards, oldest first (FIFO pairing by name). */
  openToolIds: string[];
  /** Most recently started still-running command (fallback target for
   * output/completion events that carry no item id). */
  openCommandId: string | null;
  /** All still-running command cards, oldest first (paired by item id). */
  openCommandIds: string[];
  turn: TurnState;
  usage: UsageState | null;
  artifacts: ArtifactEntry[];
  cursor: number;
  crystalSignal: CrystalSignal | null;
  /** MCP transport declared dead (mcp_down event); cleared on restart. */
  mcpDown: boolean;
  /** Latest ready row per server in this thread's current startup cycle. */
  mcpReadyIds: Record<string, string | null>;
  /** codex is compacting the conversation right now (auto or /compact) */
  compacting: boolean;
  /** detached solver jobs of this project (run_shelxt detach=true), by
   * job name: running, finished-unadopted, adopted (2026-09-18) */
  backgroundJobs: Record<string, BackgroundJobInfo>;
  /** the one system row per job, updated in place */
  backgroundJobRowIds: Record<string, string>;
  /** Rolling last-seen model metrics (advanced by state-changing tools). */
  metricsCursor: MetricsSnapshot;
  /** internal monotonic counters */
  nextId: number;
  signalSeq: number;
  /** transcript-tail dedup structures (rebuilt at bootstrap) */
  dedupKeys: ReadonlySet<string>;
  dedupUsers: ReadonlyArray<{ text: string; ts: number }>;
  /** Event identity (round-3 R1): highest eid applied and the most recent
   * eids, so a live replay of a transcript line is dropped exactly, and an
   * out-of-order neighbour inside the window is not mistaken for a replay. */
  maxEid: number;
  recentEids: ReadonlySet<number>;
  /** every non-delta event applied, in order - the source for rebuilding
   * after an older transcript page is prepended */
  rawEvents: ReadonlyArray<WbEvent>;
  /** server-side transcript paging state */
  page: PageState;
  /** live channel numbering token the state was built against */
  generation: string | null;
}

export interface PageState {
  total: number | null;
  oldestEid: number | null;
  hasMore: boolean;
  loading: boolean;
}

export type ThreadAction =
  | {
      type: "bootstrap";
      events: WbEvent[];
      reset: boolean;
      page?: Partial<PageState>;
      generation?: string | null;
      cursor?: number;
      /** server truth: is a turn running on this thread right now? When
       * false, a transcript ending mid-turn is a cut transcript. */
      busy?: boolean;
    }
  /** an older transcript page arrived: rebuild from it + everything known */
  | { type: "prepend"; events: WbEvent[]; page: Partial<PageState> }
  | { type: "page_loading"; loading: boolean }
  | { type: "event"; ev: WbEvent; seq: number }
  | {
      type: "stream";
      agentDelta?: string;
      /** legacy single buffer (routed to the newest running command) */
      commandDelta?: string;
      /** per-command output buffers, in arrival order */
      commandDeltas?: Array<{ itemId: string | null; delta: string }>;
    }
  | { type: "channel"; status: ChannelStatus }
  | { type: "approval_gone"; approvalId: string }
  | {
      type: "optimistic_user";
      id: string;
      text: string;
      steer: boolean;
      attachments?: string[];
    }
  | { type: "artifacts"; artifacts: ArtifactEntry[] };

/** Tools whose successful completion changes the crystal model or the node
 * the pane is looking at: the crystal pane (P2) refreshes on this signal and
 * only these tools may advance the turn digest's metrics cursor (a read-only
 * tool's result can carry look-alike numbers - round-2 evidence D20).
 *
 * = registry.MUTATING_TOOLS (server side, auto-commits a node) plus the
 * five UI-only extras listed last. tests/test_ui_tool_sets.py fails when the
 * two drift (D21: model_disorder / set_twin / change_space_group were
 * missing here, so their results never refreshed the pane). */
export const CRYSTAL_MUTATING: ReadonlySet<string> = new Set([
  "add_atoms_from_difference_map",
  "add_hydrogens",
  "assemble_asu",
  "change_space_group",
  "edit_atoms",
  "fit_fragment",
  "accept_fragment_pose",
  "fourier_complete",
  "interpret_peaks",
  "invert_structure",
  "model_disorder",
  "optimize_weights",
  "refine",
  "rename_atoms",
  "run_shelxl",
  "run_shelxt",
  "set_adp",
  "set_afix",
  "set_resolution_limit",
  "set_restraints",
  "set_site_occupancy",
  "set_twin",
  "set_weights",
  "set_z",
  "solvent_mask",
  "swap_reflection_data",
  // UI-only extras: change the node/branch/model the pane shows without
  // auto-committing a node on the server
  "branch",
  "checkout",
  "create_start_model",
  "import_cif_model",
  "write_outputs",
]);

const DEDUP_TAIL = 80;
const COMMAND_OUTPUT_CAP = 16000;
/** eids kept for exact replay detection; anything older than
 * maxEid - EID_WINDOW is a replay by definition (eids only grow) */
const EID_WINDOW = 512;

export function initialThreadState(threadId: string): ThreadState {
  return {
    threadId,
    subagents: [],
    channel: "connecting",
    items: [],
    itemIndex: {},
    openAgentId: null,
    openToolId: null,
    openToolIds: [],
    openCommandId: null,
    openCommandIds: [],
    turn: {
      active: false,
      taskId: null,
      startedTs: null,
      endStatus: null,
      durationMs: null,
    },
    usage: null,
    artifacts: [],
    cursor: 0,
    crystalSignal: null,
    mcpDown: false,
    mcpReadyIds: {},
    compacting: false,
    backgroundJobs: {},
    backgroundJobRowIds: {},
    metricsCursor: {},
    nextId: 1,
    signalSeq: 0,
    dedupKeys: new Set(),
    dedupUsers: [],
    maxEid: 0,
    recentEids: new Set(),
    rawEvents: [],
    page: { total: null, oldestEid: null, hasMore: false, loading: false },
    generation: null,
  };
}

// ------------------------------------------------------------ draft helpers
// The reducer copies state + items once per action, then mutates the copy.

type Draft = ThreadState & {
  items: ChatItem[];
  itemIndex: Record<string, number>;
};

function draftOf(state: ThreadState): Draft {
  return {
    ...state,
    turn: { ...state.turn },
    items: state.items.slice(),
    itemIndex: { ...state.itemIndex },
    openToolIds: state.openToolIds.slice(),
    openCommandIds: state.openCommandIds.slice(),
  };
}

/** Lifecycle events kept per card for the "原始事件" fold-out. */
const RAW_CAP = 8;

function withRaw(raw: readonly WbEvent[] | undefined, ev: WbEvent): WbEvent[] {
  const next = [...(raw ?? []), ev];
  return next.length > RAW_CAP ? next.slice(-RAW_CAP) : next;
}

function evItemId(ev: WbEvent): string | null {
  const v = (ev as { item_id?: unknown }).item_id;
  return typeof v === "string" && v !== "" ? v : null;
}

function push(st: Draft, item: ChatItem): void {
  st.itemIndex[item.id] = st.items.length;
  st.items.push(item);
}

function newId(st: Draft): string {
  const id = `i${st.nextId}`;
  st.nextId += 1;
  return id;
}

function itemById<T extends ChatItem>(st: Draft, id: string | null): T | null {
  if (id === null) return null;
  const idx = st.itemIndex[id];
  if (idx === undefined) return null;
  return (st.items[idx] as T) ?? null;
}

/** Replace item at its index with a shallow-copied, updated version. */
function update<T extends ChatItem>(st: Draft, item: T, patch: Partial<T>): T {
  const idx = st.itemIndex[item.id];
  const next = { ...item, ...patch };
  if (idx !== undefined) st.items[idx] = next;
  return next;
}

function elapsedBetween(startTs: number, endTs: number): number | null {
  if (!Number.isFinite(startTs) || !Number.isFinite(endTs)) return null;
  const startMs = startTs > 1e12 ? startTs : startTs * 1000;
  const endMs = endTs > 1e12 ? endTs : endTs * 1000;
  return endMs >= startMs ? endMs - startMs : null;
}

/** How a still-running row is closed at a turn boundary. `interrupted`:
 * the turn was stopped or failed while it ran. `no_result`: the turn ended
 * normally (or the transcript was cut) and this call's completion event
 * never arrived; the UI says so in words instead of spinning or pretending
 * success. */
export type CloseOutcome = "interrupted" | "no_result";

/** Close every live presentation row at a turn boundary. A missing completion
 * is recorded as interrupted / no result, never inferred to be a successful
 * scientific operation. This also repairs terminal transcript tails that
 * retained running cards after a disconnect or stop. */
function closeStreams(st: Draft, endedTs: number, outcome: CloseOutcome = "interrupted"): void {
  const agent = itemById<AgentItem>(st, st.openAgentId);
  if (agent && agent.streaming) update(st, agent, { streaming: false });
  // Include orphan updates and parallel commands, not just the latest cursor.
  for (let i = st.items.length - 1; i >= 0; i -= 1) {
    const item = st.items[i];
    if (item.type === "turn") break;
    if (item.type === "tool" && item.status === "running") {
      update(st, item, {
        status: outcome,
        durationMs: item.durationMs ?? elapsedBetween(item.ts, endedTs),
        ok: null,
        progressLine: null,
      });
    } else if (item.type === "command" && !item.done) {
      update(st, item, { status: outcome, done: true });
    } else if (item.type === "generic" && !item.done) {
      update(st, item, { phase: outcome, done: true });
    }
  }
  st.openAgentId = null;
  st.openToolId = null;
  st.openToolIds = [];
  st.openCommandId = null;
  st.openCommandIds = [];
}

/** The outcome for rows still running when a turn ends with `status`. */
function outcomeForTurnEnd(status: string): CloseOutcome {
  return /^(interrupted|cancelled|canceled|aborted|stopped|failed)$/.test(status)
    ? "interrupted"
    : "no_result";
}

/** The open tool card a lifecycle event belongs to: by codex item id when
 * both sides carry one (tools run concurrently and completions arrive out
 * of start order), else the oldest open card of the same (server, tool),
 * the only rule available for transcripts written before item ids. */
function matchOpenTool(
  st: Draft,
  server: string | null,
  tool: string,
  itemId: string | null,
): ToolCardItem | null {
  if (itemId !== null) {
    for (const id of st.openToolIds) {
      const card = itemById<ToolCardItem>(st, id);
      if (card && card.itemId === itemId) return card;
    }
  }
  // an id-carrying event only falls back to an id-less card of the same
  // name (mixed transcripts); it never steals another id-carrying card
  for (const id of st.openToolIds) {
    const card = itemById<ToolCardItem>(st, id);
    if (!card || card.server !== server || card.tool !== tool) continue;
    if (itemId === null || card.itemId === null) return card;
  }
  return null;
}

function removeOpenTool(st: Draft, id: string): void {
  st.openToolIds = st.openToolIds.filter((x) => x !== id);
  if (st.openToolId === id) {
    st.openToolId = st.openToolIds.at(-1) ?? null;
  }
}

/** The open command card an output/completion event belongs to: by item
 * id when the event carries one; otherwise the newest running command
 * (old transcripts / servers). */
function matchOpenCommand(st: Draft, itemId: string | null): CommandCardItem | null {
  if (itemId !== null) {
    for (const id of st.openCommandIds) {
      const card = itemById<CommandCardItem>(st, id);
      if (card && card.itemId === itemId) return card;
    }
    return null;
  }
  return itemById<CommandCardItem>(st, st.openCommandId);
}

function removeOpenCommand(st: Draft, id: string): void {
  st.openCommandIds = st.openCommandIds.filter((x) => x !== id);
  if (st.openCommandId === id) {
    st.openCommandId = st.openCommandIds.at(-1) ?? null;
  }
}

function errorText(err: unknown): string {
  if (typeof err === "string") return err;
  if (err && typeof err === "object") {
    const rec = err as Record<string, unknown>;
    if (typeof rec.message === "string") return rec.message;
    try {
      return JSON.stringify(err);
    } catch {
      /* fallthrough */
    }
  }
  return String(err ?? "");
}

function findApproval(st: Draft, approvalId: string): ApprovalItem | null {
  for (let i = st.items.length - 1; i >= 0; i -= 1) {
    const it = st.items[i];
    if (it.type === "approval" && it.approvalId === approvalId) return it;
  }
  return null;
}

function lastOpenGeneric(st: Draft, family: string, itemId: string | null): GenericItem | null {
  let fallback: GenericItem | null = null;
  for (let i = st.items.length - 1; i >= 0; i -= 1) {
    const it = st.items[i];
    if (it.type === "generic" && it.family === family && !it.done) {
      if (itemId !== null && it.itemId === itemId) return it;
      if (fallback === null && (itemId === null || !it.itemId)) fallback = it;
    }
    // stop scanning past a different completed block boundary? keep simple:
    if (it.type === "turn") break;
  }
  return fallback;
}

/** Aggregate the just-finished turn (items after the latest turn-started
 * marker): tool call counts, committed nodes, shell command count, and the
 * R1 movement. Returns undefined for turns that ran no crystallography. */
function summarizeTurn(st: Draft): TurnAggregate | undefined {
  let startIdx = -1;
  for (let k = st.items.length - 1; k >= 0; k -= 1) {
    const it = st.items[k];
    if (it.type === "turn" && it.phase === "started") {
      startIdx = k;
      break;
    }
  }
  if (startIdx < 0) return undefined;
  const tools = new Map<string, number>();
  const nodes: string[] = [];
  let nCommands = 0;
  let r1From: number | null = null;
  for (let k = startIdx + 1; k < st.items.length; k += 1) {
    const it = st.items[k];
    if (it.type === "tool") {
      tools.set(it.tool, (tools.get(it.tool) ?? 0) + 1);
      const node = it.status === "ok" ? it.summary?.node : undefined;
      if (typeof node === "string" && !nodes.includes(node)) nodes.push(node);
      if (r1From === null && it.metricsBefore?.r1 !== undefined) {
        r1From = it.metricsBefore.r1 ?? null;
      }
    } else if (it.type === "command") {
      nCommands += 1;
    }
  }
  if (tools.size === 0 && nCommands === 0) return undefined;
  return {
    tools: [...tools.entries()].sort((a, b) => b[1] - a[1]),
    nodes,
    nCommands,
    r1From,
    r1To: st.metricsCursor.r1 ?? null,
  };
}

// --------------------------------------------------------------- event fold

function applyEvent(st: Draft, ev: WbEvent, seq: number): void {
  const firstNewItem = st.items.length;
  foldEvent(st, ev, seq);
  if (typeof ev.eid === "number" && ev.eid > 0) {
    for (let i = firstNewItem; i < st.items.length; i += 1) {
      st.items[i] = { ...st.items[i], eid: ev.eid };
    }
  }
}

function foldEvent(st: Draft, ev: WbEvent, seq: number): void {
  switch (ev.kind) {
    case "user_message":
    case "user_steer": {
      const steer =
        ev.kind === "user_steer" || ("steer" in ev && ev.steer === true);
      const attachments =
        ev.attachments && ev.attachments.length > 0
          ? ev.attachments
          : undefined;
      // reconcile a pending optimistic bubble by text match
      for (let i = st.items.length - 1; i >= 0; i -= 1) {
        const it = st.items[i];
        if (it.type === "user" && it.pending && it.text === ev.text) {
          update(st, it, { pending: false, steer, ts: ev.ts, attachments, eid: ev.eid });
          return;
        }
      }
      push(st, {
        type: "user",
        id: newId(st),
        ts: ev.ts,
        text: ev.text,
        steer,
        pending: false,
        attachments,
        eid: ev.eid,
      });
      return;
    }

    case "steer_receipt": {
      // the bubble it refers to: by transcript eid, else the latest steer
      // still without a receipt (live events before the eid stamp)
      let target: UserItem | null = null;
      if (ev.steer_eid !== undefined) {
        for (let i = st.items.length - 1; i >= 0; i -= 1) {
          const it = st.items[i];
          if (it.type === "user" && it.eid === ev.steer_eid) {
            target = it;
            break;
          }
        }
      }
      if (target === null) {
        for (let i = st.items.length - 1; i >= 0; i -= 1) {
          const it = st.items[i];
          if (it.type === "user" && it.steer && it.receipt === undefined) {
            target = it;
            break;
          }
        }
      }
      if (target !== null) {
        update(st, target, {
          receipt: ev.status,
          receiptError: ev.status === "failed" ? ev.error : undefined,
        });
      }
      return;
    }

    case "turn_started": {
      // rows still running when the next turn starts never got their end
      // event (we missed it or the previous turn end was never seen)
      closeStreams(st, ev.ts, "no_result");
      st.turn = {
        active: true,
        taskId: ev.task_id ?? st.turn.taskId,
        startedTs: ev.ts,
        endStatus: null,
        durationMs: null,
      };
      push(st, {
        type: "turn",
        id: newId(st),
        ts: ev.ts,
        phase: "started",
        status: null,
        durationMs: null,
        error: null,
      });
      return;
    }

    case "turn_completed": {
      const status = normalizeEnum(ev.status) || "completed";
      closeStreams(st, ev.ts, outcomeForTurnEnd(status));
      st.turn = {
        ...st.turn,
        active: false,
        endStatus: status,
        durationMs: ev.duration_ms,
      };
      // refresh crystal data on EVERY turn end: mutations that bypass the
      // MCP stream (direct invoke shims, shell-driven stages) commit real
      // nodes that tool-event signals never see (observed live: a 50-node
      // run whose tree stayed at n0000 all the way to delivery)
      st.signalSeq += 1;
      st.crystalSignal = { seq: st.signalSeq, tool: "turn" };
      push(st, {
        type: "turn",
        id: newId(st),
        ts: ev.ts,
        phase: status === "failed" ? "failed" : "completed",
        status,
        durationMs: ev.duration_ms,
        // failed turns now carry the provider error (e.g. gateway 401 /
        // unsupported reasoning effort) - surface it instead of a bare
        // "failed" chip
        error: errorText(ev.error) || null,
        summary: summarizeTurn(st),
      });
      return;
    }

    case "turn_failed": {
      closeStreams(st, ev.ts);
      st.turn = { ...st.turn, active: false, endStatus: "failed" };
      push(st, {
        type: "turn",
        id: newId(st),
        ts: ev.ts,
        phase: "failed",
        status: "failed",
        durationMs: null,
        error: errorText(ev.error),
      });
      return;
    }

    case "agent_message": {
      const open = itemById<Extract<ChatItem, { type: "agent" }>>(st, st.openAgentId);
      if (open) {
        // authoritative text replaces whatever streamed in
        update(st, open, {
          text: ev.text, streaming: false, ts: ev.ts,
          ...(typeof ev.eid === "number" && ev.eid > 0 ? { eid: ev.eid } : {}),
        });
        st.openAgentId = null;
      } else {
        push(st, {
          type: "agent",
          id: newId(st),
          ts: ev.ts,
          text: ev.text,
          streaming: false,
          ...(seq > 0 ? { renderId: `agent:${ev.ts}:${seq}` } : {}),
        });
      }
      return;
    }

    case "reasoning_summary": {
      push(st, { type: "reasoning", id: newId(st), ts: ev.ts, text: ev.text });
      return;
    }

    case "tool_started": {
      const id = newId(st);
      push(st, {
        type: "tool",
        id,
        ts: ev.ts,
        server: ev.server,
        tool: ev.tool,
        args: ev.args,
        status: "running",
        rawStatus: normalizeEnum(ev.status) || "in_progress",
        durationMs: ev.duration_ms,
        ok: ev.ok,
        resultTail: ev.result_tail,
        error: ev.error,
        progressLine: null,
        summary: null,
        metricsBefore: null,
        itemId: evItemId(ev),
        raw: [ev],
      });
      st.openToolId = id;
      st.openToolIds.push(id);
      return;
    }

    case "tool_progress": {
      const iid = evItemId(ev);
      let open: ToolCardItem | null = null;
      if (iid !== null) {
        for (const id of st.openToolIds) {
          const card = itemById<ToolCardItem>(st, id);
          if (card && card.itemId === iid) { open = card; break; }
        }
      }
      if (open === null && iid === null) open = itemById<ToolCardItem>(st, st.openToolId);
      if (open) update(st, open, { progressLine: ev.message ?? null });
      return;
    }

    case "tool_updated":
    case "tool_completed": {
      const completed = ev.kind === "tool_completed";
      const iid = evItemId(ev);
      const open = matchOpenTool(st, ev.server, ev.tool, iid);
      const rawStatus =
        normalizeEnum(ev.status) || (completed ? "completed" : "");
      const summary = completed ? safeParseResultTail(ev.result_tail) : null;
      const interrupted = /^(interrupted|cancelled|canceled|aborted|stopped)$/.test(rawStatus);
      const failed =
        ev.ok === false || ev.error !== null || rawStatus === "failed";
      const status = !completed ? "running" : failed ? "error" : interrupted ? "interrupted" : "ok";
      // stamp the pre-completion metrics cursor, then advance it (only for
      // successful model-changing tools: a read-only tool such as
      // validate_structure or compare_nodes reports scores and deltas whose
      // keys look like metrics - D20)
      const hasMetrics =
        summary !== null &&
        (summary.r1 !== undefined ||
          summary.wr2 !== undefined ||
          summary.goof !== undefined);
      const metricsBefore = status === "ok" && hasMetrics ? st.metricsCursor : null;
      if (
        status === "ok" &&
        hasMetrics &&
        summary.noStateChange !== true &&
        CRYSTAL_MUTATING.has(ev.tool)
      ) {
        st.metricsCursor = {
          ...st.metricsCursor,
          ...(summary.r1 !== undefined ? { r1: summary.r1 } : {}),
          ...(summary.wr2 !== undefined ? { wr2: summary.wr2 } : {}),
          ...(summary.goof !== undefined ? { goof: summary.goof } : {}),
          ...(summary.diffMapMax !== undefined
            ? { diffMapMax: summary.diffMapMax }
            : {}),
          ...(summary.nParams !== undefined
            ? { nParams: summary.nParams }
            : {}),
        };
      }
      const patch: Partial<ToolCardItem> = {
        rawStatus,
        durationMs: ev.duration_ms,
        ok: ev.ok,
        resultTail: ev.result_tail,
        error: ev.error,
        ...(completed
          ? {
              status,
              progressLine: null,
              summary,
              metricsBefore,
            }
          : {}),
      };
      if (open) {
        update(st, open, {
          ...patch,
          raw: withRaw(open.raw, ev),
          ...(open.itemId === null && iid !== null ? { itemId: iid } : {}),
        });
        if (completed) removeOpenTool(st, open.id);
      } else {
        // A transcript page can start with an update rather than its start.
        const id = newId(st);
        if (!completed) {
          st.openToolIds.push(id);
          st.openToolId = id;
        }
        push(st, {
          type: "tool",
          id,
          ts: ev.ts,
          server: ev.server,
          tool: ev.tool,
          args: ev.args,
          status,
          rawStatus,
          durationMs: ev.duration_ms,
          ok: ev.ok,
          resultTail: ev.result_tail,
          error: ev.error,
          progressLine: null,
          summary,
          metricsBefore,
          itemId: iid,
          raw: [ev],
        });
      }
      if (status === "ok" && ev.ok === true && ev.tool === "run_shelxt") {
        noteJobAdoption(st, ev.args, summary);
      }
      if (status === "ok" && ev.ok === true && CRYSTAL_MUTATING.has(ev.tool)) {
        st.signalSeq += 1;
        st.crystalSignal = {
          seq: seq > 0 ? seq : st.signalSeq,
          tool: ev.tool,
          ...(summary?.node !== undefined ? { node: summary.node } : {}),
        };
      }
      return;
    }

    case "command_started": {
      const id = newId(st);
      push(st, {
        type: "command",
        id,
        ts: ev.ts,
        command: ev.command,
        status: normalizeEnum(ev.status) || "in_progress",
        exitCode: ev.exit_code,
        output: ev.output_tail ?? "",
        done: false,
        itemId: ev.item_id ?? null,
        outputLen: null,
        outputFile: null,
        raw: [ev],
      });
      st.openCommandId = id;
      st.openCommandIds.push(id);
      return;
    }

    case "command_updated": {
      // codex item/updated for a running command: status only
      const open = matchOpenCommand(st, ev.item_id ?? null);
      if (open) {
        update(st, open, {
          status: normalizeEnum(ev.status) || open.status,
          raw: withRaw(open.raw, ev),
        });
      }
      return;
    }

    case "command_completed": {
      // pair by codex item id: commands run concurrently and finish out of
      // start order (test4-0909 eids 2141/2146/2151 -> 2154/2155); the old
      // "newest running card" rule painted A's result on B and left A
      // spinning forever
      const open = matchOpenCommand(st, ev.item_id ?? null);
      const status = normalizeEnum(ev.status) || "completed";
      const tail = ev.output_tail ?? "";
      if (open) {
        // the streamed text is a superset of the 1500-char completion tail;
        // replacing it used to throw away up to 16k chars (forensics F-6)
        const output = open.output.length > tail.length ? open.output : tail;
        update(st, open, {
          status,
          exitCode: ev.exit_code,
          output,
          done: true,
          itemId: ev.item_id ?? open.itemId,
          outputLen: ev.output_len ?? null,
          outputFile: ev.output_file ?? null,
          raw: withRaw(open.raw, ev),
        });
        removeOpenCommand(st, open.id);
      } else {
        push(st, {
          type: "command",
          id: newId(st),
          ts: ev.ts,
          command: ev.command,
          status,
          exitCode: ev.exit_code,
          output: tail,
          done: true,
          itemId: ev.item_id ?? null,
          outputLen: ev.output_len ?? null,
          outputFile: ev.output_file ?? null,
          raw: [ev],
        });
      }
      return;
    }

    case "approval_request": {
      if (findApproval(st, ev.approval_id)) return; // rehydration duplicate
      push(st, {
        type: "approval",
        id: newId(st),
        ts: ev.ts,
        approvalId: ev.approval_id,
        method: ev.method,
        detail: ev.detail,
        mcpServer: ev.mcp_server ?? null,
        mcpMessage: ev.mcp_message ?? null,
        mcpToolParams: ev.mcp_tool_params ?? null,
        status: "pending",
      });
      return;
    }

    case "approval_decision": {
      const item = findApproval(st, ev.approval_id);
      const accepted =
        ev.decision === "accept" || ev.decision === "accept_for_session";
      const status: ApprovalStatus = accepted
        ? ev.auto === true
          ? "auto"
          : "accepted"
        : "rejected";
      if (item) {
        if (item.status === "pending" || status !== "accepted") {
          update(st, item, { status });
        }
      } else if (ev.auto === true) {
        // session-allow auto decision without a visible request
        push(st, {
          type: "generic",
          id: newId(st),
          ts: ev.ts,
          kind: "approval_auto",
          family: "approval_auto",
          phase: "completed",
          detail: null,
          done: true,
        });
      }
      return;
    }

    case "approval_timeout": {
      const item = findApproval(st, ev.approval_id);
      if (item && item.status === "pending")
        update(st, item, { status: "timeout" });
      return;
    }

    case "token_usage": {
      st.usage = {
        last: ev.last,
        total: ev.total,
        contextWindow: ev.context_window,
      };
      return;
    }

    case "idle": {
      // idle after a turn end whose completion we never saw: the rows
      // still running got no result, they were not interrupted
      closeStreams(st, ev.ts, "no_result");
      st.turn = { ...st.turn, active: false };
      if (Array.isArray(ev.artifacts)) st.artifacts = ev.artifacts;
      return;
    }

    case "client_error": {
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: "client_error",
        family: "client_error",
        phase: "completed",
        detail: ev.error,
        done: true,
      });
      return;
    }

    case "agent_delta": {
      // normally handled via the batched stream action; direct events (e.g.
      // from tests) fold the same way
      applyAgentDelta(st, ev.delta);
      return;
    }

    case "command_output": {
      applyCommandDelta(st, ev.delta);
      return;
    }

    // project-level notices -> centered system rows (Codex style)
    case "permission_mode": {
      // the same mode announced twice in a row (settings echo + rebuild
      // echo) is one fact - one row (seen live: three 权限模式已切换 rows)
      const last = st.items.at(-1);
      if (
        last &&
        last.type === "generic" &&
        last.kind === "permission_mode" &&
        (last.detail as { mode?: unknown } | null)?.mode === ev.mode
      ) {
        return;
      }
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: { mode: ev.mode, rebuilt: ev.rebuilt },
        done: true,
      });
      return;
    }

    // subagent activity (codex multi-agent): one row per spawn / wait /
    // send / close plus the registry the header directory reads
    case "collab_started":
    case "collab_updated":
    case "collab_completed": {
      const done = ev.kind === "collab_completed";
      const receivers = ev.receivers ?? [];
      const states = ev.agents_states ?? {};
      const subs = st.subagents.slice();
      const isSpawn = (ev.tool ?? "").toLowerCase().includes("spawn");
      for (const rid of receivers) {
        const idx = subs.findIndex((s) => s.id === rid);
        const stMsg = states[rid]?.message ?? null;
        const stStatus = states[rid]?.status ?? null;
        if (idx === -1) {
          subs.push({
            id: rid,
            prompt: isSpawn ? ev.prompt : null,
            model: ev.model,
            effort: ev.reasoning_effort,
            status: stStatus ?? (done ? "spawned" : "starting"),
            startedTs: ev.ts,
            endedTs: null,
            message: stMsg,
          });
        } else {
          const cur = subs[idx];
          const closing = (ev.tool ?? "").toLowerCase().includes("close");
          subs[idx] = {
            ...cur,
            prompt: cur.prompt ?? (isSpawn ? ev.prompt : null),
            status: stStatus ?? (closing && done ? "closed" : cur.status),
            message: stMsg ?? cur.message,
            endedTs: closing && done ? ev.ts : cur.endedTs,
          };
        }
      }
      // states may name agents no receivers list mentioned (wait on all)
      for (const [rid, s] of Object.entries(states)) {
        const idx = subs.findIndex((x) => x.id === rid);
        if (idx === -1) continue;
        const cur = subs[idx];
        const finished =
          s?.status !== undefined &&
          /completed|done|closed|failed|error/i.test(String(s.status));
        subs[idx] = {
          ...cur,
          status: s?.status ?? cur.status,
          message: s?.message ?? cur.message,
          endedTs: finished && cur.endedTs === null ? ev.ts : cur.endedTs,
        };
      }
      st.subagents = subs;
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "collab",
        phase: done ? "completed" : "started",
        detail: {
          tool: ev.tool,
          receivers,
          prompt: ev.prompt,
          model: ev.model,
          effort: ev.reasoning_effort,
          status: ev.status,
        },
        done,
      });
      return;
    }

    case "specialists_toggled": {
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: { enabled: ev.enabled },
        done: true,
      });
      return;
    }

    case "delegation": {
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: { active: ev.active, roles_written: ev.roles_written ?? [] },
        done: true,
      });
      return;
    }

    // engine health: banner state + a centered system row for the record
    case "mcp_down": {
      st.mcpReadyIds = {};
      if (!st.mcpDown) {
        st.mcpDown = true;
        push(st, {
          type: "generic",
          id: newId(st),
          ts: ev.ts,
          kind: ev.kind,
          family: "system",
          phase: "completed",
          detail: { message: ev.message },
          done: true,
        });
      }
      return;
    }

    case "mcp_startup": {
      const server = ev.server ?? "";
      const status = normalizeEnum(ev.status);
      if (status === "starting" || status === "waiting") {
        st.mcpReadyIds = { ...st.mcpReadyIds, [server]: null };
      }
      if (!["waiting", "ready", "timeout", "failed", "error"].includes(status)) return;
      const nTools = typeof ev.n_tools === "number" && Number.isInteger(ev.n_tools) && ev.n_tools >= 0 ? ev.n_tools : null;
      const detail = {
        server, status, n_tools: nTools,
        seconds: ev.seconds ?? null, error: ev.error ?? null,
      };
      const previous = itemById<GenericItem>(st, st.mcpReadyIds[server] ?? null);
      if (status === "ready" && previous) {
        // Native notifications can repeat; service probes may enrich the same
        // ready fact with a real count. Never erase a count with an unknown.
        const known = previous.detail as typeof detail;
        update(st, previous, { detail: { ...detail, n_tools: nTools ?? known.n_tools, seconds: detail.seconds ?? known.seconds } });
        return;
      }
      const id = newId(st);
      st.mcpReadyIds = { ...st.mcpReadyIds, [server]: status === "ready" ? id : null };
      push(st, {
        type: "generic", id, ts: ev.ts, kind: ev.kind,
        family: "system", phase: "completed", detail, done: true,
      });
      return;
    }

    case "background_job": {
      // one system row per detached solver job, rewritten in place on
      // every transition / heartbeat; always `done` so a turn boundary
      // never marks it interrupted - the job outlives the turn by design
      const job = typeof ev.job === "string" ? ev.job : "";
      if (!job) return;
      const info = jobInfoFromEvent(ev, st.backgroundJobs[job] ?? null);
      st.backgroundJobs = { ...st.backgroundJobs, [job]: info };
      const row = itemById<GenericItem>(st, st.backgroundJobRowIds[job] ?? null);
      const phase = info.running ? "running" : info.error ? "failed" : "completed";
      if (row) {
        update(st, row, { detail: info, phase });
        return;
      }
      const id = newId(st);
      st.backgroundJobRowIds = { ...st.backgroundJobRowIds, [job]: id };
      push(st, {
        type: "generic", id, ts: ev.ts, kind: "background_job",
        family: "system", phase, detail: info, done: true,
      });
      return;
    }

    case "engine_restarted": {
      st.mcpDown = false;
      st.mcpReadyIds = {};
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: null,
        done: true,
      });
      return;
    }

    case "compaction_requested":
    case "compaction_started":
    case "compaction_completed": {
      st.compacting = ev.kind === "compaction_started";
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: { manual: ev.manual === true },
        done: true,
      });
      return;
    }

    case "engine_warning":
    case "model_rerouted": {
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: ev.kind,
        family: "system",
        phase: "completed",
        detail: { ...ev },
        done: true,
      });
      return;
    }

    // client-local card (slash command output), never on the wire
    case "note": {
      push(st, {
        type: "generic",
        id: newId(st),
        ts: ev.ts,
        kind: "note",
        family: "system",
        phase: "completed",
        detail: { title: ev.title, lines: ev.lines },
        done: true,
      });
      return;
    }

    // project-level bookkeeping the WorkbenchProvider consumes
    case "settings":
    case "config_changed":
    case "thread_status":
    case "thread_renamed":
    case "background_turn_completed":
      return;

    case "file_change_started":
    case "file_change_updated":
    case "file_change_completed":
    case "webSearch_started":
    case "webSearch_updated":
    case "webSearch_completed":
    case "todoList_started":
    case "todoList_updated":
    case "todoList_completed":
    case "error_started":
    case "error_updated":
    case "error_completed":
    case "imageView_started":
    case "imageView_updated":
    case "imageView_completed": {
      const us = ev.kind.lastIndexOf("_");
      const family = ev.kind.slice(0, us);
      const phase = ev.kind.slice(us + 1);
      const detail =
        "detail" in ev ? ev.detail : "changes" in ev ? ev.changes : null;
      const iid = evItemId(ev);
      const open = phase === "started" ? null : lastOpenGeneric(st, family, iid);
      if (open) {
        update(st, open, {
          phase, detail, done: phase === "completed",
          ...(iid !== null && !open.itemId ? { itemId: iid } : {}),
        });
      } else {
        push(st, {
          type: "generic",
          id: newId(st),
          ts: ev.ts,
          kind: ev.kind,
          family,
          phase,
          detail,
          done: phase === "completed",
          itemId: iid,
        });
      }
      return;
    }

    case "ping":
    case "channel_closed":
      // transport-level: handled by the channel hook, nothing to render
      return;

    default:
      // unknown future kinds: ignore rather than crash
      return;
  }
}

/** run_shelxt(from_job=<job>) succeeded: that background job's solution
 * is now the session model - the row stops asking for adoption. The
 * server emits an `adopted` transition too (from the registry); this is
 * the client-side echo that also knows the node id. */
function noteJobAdoption(st: Draft, args: unknown, summary: ResultSummary | null): void {
  const a = (args ?? {}) as { from_job?: unknown };
  const job = jobNameFromArg(a.from_job);
  if (!job) return;
  const prev = st.backgroundJobs[job];
  if (!prev) return;
  const node = summary && typeof summary.node === "string" ? summary.node : null;
  const info: BackgroundJobInfo = { ...prev, adopted: true, adoptedNode: node ?? prev.adoptedNode };
  st.backgroundJobs = { ...st.backgroundJobs, [job]: info };
  const row = itemById<GenericItem>(st, st.backgroundJobRowIds[job] ?? null);
  if (row) update(st, row, { detail: info, phase: "completed" });
}

function applyAgentDelta(st: Draft, delta: string): void {
  if (delta === "") return;
  const open = itemById<AgentItem>(st, st.openAgentId);
  if (open) {
    update(st, open, { text: open.text + delta });
  } else {
    const id = newId(st);
    push(st, {
      type: "agent",
      id,
      ts: Date.now() / 1000,
      text: delta,
      streaming: true,
      renderId: `agent:stream:${id}:${Date.now()}`,
    });
    st.openAgentId = id;
  }
}

function applyCommandDelta(st: Draft, delta: string, itemId: string | null = null): void {
  if (delta === "") return;
  const open = matchOpenCommand(st, itemId);
  if (!open) return; // command output without an open command card: drop
  let output = open.output + delta;
  if (output.length > COMMAND_OUTPUT_CAP)
    output = output.slice(-COMMAND_OUTPUT_CAP);
  update(st, open, { output });
}

// ----------------------------------------------------------------- reducer

function eventKey(ev: WbEvent): string {
  return `${ev.kind}|${ev.ts}`;
}

function noteEid(st: Draft, eid: number | undefined): void {
  if (typeof eid !== "number" || eid <= 0) return;
  // copy-on-write (bounded, so cheap): a reducer must not mutate the
  // previous state - StrictMode replays it and would see its own marks
  const next = new Set(st.recentEids);
  next.add(eid);
  if (next.size > EID_WINDOW) {
    const first = next.values().next();
    if (!first.done) next.delete(first.value);
  }
  st.recentEids = next;
  if (eid > st.maxEid) st.maxEid = eid;
}

function isEvent(ev: unknown): ev is WbEvent {
  return !!ev && typeof ev === "object" && "kind" in ev;
}

/** Bootstrap / prepend share this: replay events into a fresh state that
 * keeps the connection-level fields of the previous one. */
function rebuild(
  state: ThreadState,
  events: ReadonlyArray<WbEvent>,
  opts: {
    reset: boolean;
    page?: Partial<PageState>;
    generation?: string | null;
    cursor?: number;
    busy?: boolean;
  },
): ThreadState {
  const base = opts.reset
    ? {
        ...initialThreadState(state.threadId),
        channel: state.channel,
        artifacts: state.artifacts,
        usage: state.usage,
        cursor: state.cursor,
        generation: state.generation,
        page: state.page,
      }
    : state;
  const st = draftOf(base);
  const applied: WbEvent[] = opts.reset ? [] : [...state.rawEvents];
  for (const ev of events) {
    if (!isEvent(ev) || ev.kind === "channel_hello") continue;
    applyEvent(st, ev, 0);
    applied.push(ev);
  }
  // transcripts never contain deltas; nothing should be left streaming
  // unless a turn is genuinely in flight. A transcript that ends mid-turn
  // while the server says the thread is idle was cut (restart, crash): its
  // running rows never got an end event and say so.
  if (st.turn.active && opts.busy === false) {
    closeStreams(st, applied.at(-1)?.ts ?? 0, "no_result");
    st.turn = { ...st.turn, active: false, endStatus: st.turn.endStatus ?? "unknown" };
  } else if (!st.turn.active) {
    closeStreams(st, applied.at(-1)?.ts ?? 0, "no_result");
  }
  const tail = applied.slice(-DEDUP_TAIL);
  st.dedupKeys = new Set(tail.map(eventKey));
  st.dedupUsers = tail
    .filter((e) => e.kind === "user_message" || e.kind === "user_steer")
    .map((e) => ({ text: (e as { text: string }).text, ts: e.ts }));
  st.rawEvents = applied;
  // Prepending history renumbers local ids. Preserve the live presentation
  // identity only when the persisted source matches, never by local id.
  const presentations = new Map(state.items.flatMap(item => item.type === "agent" && item.renderId
    ? [[item.eid !== undefined ? `eid:${item.eid}` : `legacy:${item.ts}:${item.text}`, { renderId: item.renderId, text: item.text }] as const] : []));
  st.items = st.items.map(item => {
    if (item.type !== "agent") return item;
    const old = presentations.get(item.eid !== undefined ? `eid:${item.eid}` : `legacy:${item.ts}:${item.text}`);
    return old?.text === item.text ? { ...item, renderId: old.renderId } : item;
  });
  let maxEid = 0;
  const recent = new Set<number>();
  for (const e of applied.slice(-EID_WINDOW)) {
    if (typeof e.eid === "number" && e.eid > 0) recent.add(e.eid);
  }
  for (const e of applied) {
    if (typeof e.eid === "number" && e.eid > maxEid) maxEid = e.eid;
  }
  st.recentEids = recent;
  st.maxEid = maxEid;
  if (opts.page) st.page = { ...st.page, ...opts.page, loading: false };
  if (opts.generation !== undefined) st.generation = opts.generation;
  if (opts.cursor !== undefined) st.cursor = opts.cursor;
  // Slash-command notes (/status, /context, /mcp ...) are client-local and
  // never in the transcript. A reset rebuild - the first transcript landing
  // after the user already typed a command, or a reconnect that reloads the
  // transcript - must not eat them (2026-09-16: a note issued during the
  // first second after opening a thread vanished).
  if (opts.reset) {
    for (const note of state.items) {
      if (note.type !== "generic" || note.kind !== "note") continue;
      let at = st.items.findIndex((row) => row.ts > note.ts);
      if (at < 0) at = st.items.length;
      st.items.splice(at, 0, { ...note, id: newId(st) });
    }
  }
  return st;
}

/** True when a live event is a replay of a transcript-tail event. */
function isDuplicate(st: ThreadState, ev: WbEvent): boolean {
  if (typeof ev.eid === "number" && ev.eid > 0) {
    // exact identity: the transcript line index the server stamped
    if (st.recentEids.has(ev.eid)) return true;
    return ev.eid <= st.maxEid - EID_WINDOW;
  }
  if (st.dedupKeys.has(eventKey(ev))) return true;
  if (ev.kind === "user_message" || ev.kind === "user_steer") {
    for (const u of st.dedupUsers) {
      if (u.text === ev.text && Math.abs(u.ts - ev.ts) <= 3) return true;
    }
  }
  return false;
}

export function threadReducer(
  state: ThreadState,
  action: ThreadAction,
): ThreadState {
  switch (action.type) {
    case "bootstrap":
      return rebuild(state, action.events, {
        reset: action.reset,
        page: action.page,
        generation: action.generation,
        cursor: action.cursor,
        busy: action.busy,
      });

    case "prepend": {
      // older page first, then everything this state was built from
      const older = action.events.filter(isEvent);
      if (older.length === 0) {
        return {
          ...state,
          page: { ...state.page, ...action.page, loading: false },
        };
      }
      const rebuilt = rebuild(state, [...older, ...state.rawEvents], {
        reset: true,
        page: action.page,
      });
      // Agent deltas are not stored in rawEvents. Paging while a reply is
      // playing must retain those transient rows, including interrupted tails.
      const pending = state.items.filter((item): item is AgentItem => item.type === "agent" && Boolean(item.renderId)
        && !rebuilt.items.some(row => row.type === "agent" && row.renderId === item.renderId));
      if (pending.length === 0) return rebuilt;
      const st = draftOf(rebuilt);
      const source = (item: ChatItem) => item.eid !== undefined ? `${item.type}:${item.eid}` : `${item.type}:${item.ts}`;
      for (const item of pending) {
        let at = st.items.length;
        for (const next of state.items.slice(state.items.indexOf(item) + 1)) {
          const matches = st.items.flatMap((row, i) => source(row) === source(next) ? [i] : []);
          if (matches.length === 1) { at = matches[0]; break; }
        }
        const id = newId(st);
        st.items.splice(at, 0, { ...item, id });
        if (state.openAgentId === item.id) st.openAgentId = id;
      }
      st.itemIndex = Object.fromEntries(st.items.map((item, i) => [item.id, i]));
      return st;
    }

    case "page_loading": {
      if (state.page.loading === action.loading) return state;
      return { ...state, page: { ...state.page, loading: action.loading } };
    }

    case "event": {
      if (action.ev.kind === "channel_hello" || action.ev.kind === "ping"
          || action.ev.kind === "channel_closed") return state;
      if (isDuplicate(state, action.ev)) return state;
      const st = draftOf(state);
      applyEvent(st, action.ev, action.seq);
      if (action.seq > 0) st.cursor = Math.max(st.cursor, action.seq);
      noteEid(st, action.ev.eid);
      st.rawEvents = [...state.rawEvents, action.ev];
      return st;
    }

    case "stream": {
      // live deltas only make sense inside an active turn; SSE replays of a
      // finished turn (transcript already folded) are dropped here
      if (!state.turn.active) return state;
      const st = draftOf(state);
      if (action.agentDelta !== undefined)
        applyAgentDelta(st, action.agentDelta);
      if (action.commandDelta !== undefined)
        applyCommandDelta(st, action.commandDelta);
      for (const d of action.commandDeltas ?? [])
        applyCommandDelta(st, d.delta, d.itemId);
      return st;
    }

    case "channel": {
      if (state.channel === action.status) return state;
      return { ...state, channel: action.status };
    }

    case "approval_gone": {
      const st = draftOf(state);
      const item = findApproval(st, action.approvalId);
      if (item && item.status === "pending") {
        update(st, item, { status: "resolved" });
        return st;
      }
      return state;
    }

    case "optimistic_user": {
      const st = draftOf(state);
      st.itemIndex[action.id] = st.items.length;
      st.items.push({
        type: "user",
        id: action.id,
        ts: Date.now() / 1000,
        text: action.text,
        steer: action.steer,
        pending: true,
        attachments:
          action.attachments && action.attachments.length > 0
            ? action.attachments
            : undefined,
      });
      return st;
    }

    case "artifacts": {
      return { ...state, artifacts: action.artifacts };
    }

    default:
      return state;
  }
}
