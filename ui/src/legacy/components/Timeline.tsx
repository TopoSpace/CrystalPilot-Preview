import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type UIEvent,
} from "react";
import type { EventPayload, RunEvent } from "../../lib/api";
import { approveAction } from "../../lib/api";
import {
  asNum,
  asStr,
  cx,
  fmtFixed,
  fmtInt,
  fmtSeconds,
} from "../../lib/format";
import { stageLabel, toolLabel } from "../../lib/labels";
import { Button, Chip, EmptyState, Spinner, StatusDot } from "../../components/ui";

/* ------------------------------------------------------- timeline building */

interface ChipData {
  k: string;
  v: string;
}

interface ToolResult {
  ok: boolean;
  elapsed?: number;
  chips: ChipData[];
  error?: string;
}

/** How a pending_approval was resolved, as inferred from the event stream. */
type ApprovalResolution = "approved" | "rejected" | "auto-approved";

export type LocalDecision = "approved" | "rejected";

type Item =
  | { id: string; type: "stage"; label: string; sub?: string }
  | {
      id: string;
      type: "tool";
      tool: string;
      label: string;
      params?: string;
      result?: ToolResult;
    }
  | { id: string; type: "thought"; step?: number; text: string }
  | {
      id: string;
      type: "approval";
      tool: string;
      label: string;
      params?: string;
      rationale?: string;
      resolution?: ApprovalResolution;
    }
  | { id: string; type: "note"; text: string }
  | { id: string; type: "finish"; status: string; assessment?: string };

function chip(k: string, v: string | undefined): ChipData | null {
  return v !== undefined && v !== "—" ? { k, v } : null;
}

function present(entries: Array<ChipData | null>): ChipData[] {
  return entries.filter((e): e is ChipData => e !== null);
}

function resultChips(tool: string, s: Record<string, unknown>): ChipData[] {
  switch (tool) {
    case "refine":
      return present([
        chip("R1", fmtFixed(s.r1_strong, 4)),
        chip("wR2", fmtFixed(s.wr2, 4)),
        chip("GooF", fmtFixed(s.goof, 2)),
      ]);
    case "solve_charge_flipping":
      return present([
        chip("CC", fmtFixed(s.map_correlation, 3)),
        chip("peaks", asNum(s.n_peaks) !== undefined ? fmtInt(s.n_peaks) : undefined),
      ]);
    case "interpret_peaks":
    case "edit_atoms":
      return present([
        chip("atoms", asNum(s.n_atoms) !== undefined ? fmtInt(s.n_atoms) : undefined),
      ]);
    case "add_atoms_from_difference_map": {
      const added = Array.isArray(s.added) ? s.added.length : undefined;
      return present([
        chip("added", added !== undefined ? `+${added}` : undefined),
        chip("atoms", asNum(s.n_atoms) !== undefined ? fmtInt(s.n_atoms) : undefined),
      ]);
    }
    case "validate_structure": {
      const conf = s.confidence as Record<string, unknown> | undefined;
      return present([
        chip(
          "alerts",
          asNum(s.n_alerts) !== undefined ? fmtInt(s.n_alerts) : undefined,
        ),
        chip(
          "confidence",
          asNum(conf?.score) !== undefined
            ? `${fmtFixed(conf?.score, 0)}/100`
            : undefined,
        ),
      ]);
    }
    case "determine_space_group":
    case "set_space_group":
      return present([chip("SG", asStr(s.space_group))]);
    default:
      return [];
  }
}

function datasetSub(p: EventPayload): string | undefined {
  const ds = p.dataset;
  if (!ds) return undefined;
  const parts: string[] = [];
  if (asNum(ds.n_reflections) !== undefined) {
    parts.push(`${fmtInt(ds.n_reflections)} reflections`);
  }
  if (asNum(ds.d_min) !== undefined && asNum(ds.d_max) !== undefined) {
    parts.push(`d ${ds.d_min!.toFixed(2)}–${ds.d_max!.toFixed(2)} Å`);
  }
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

function stageEndSub(p: EventPayload): string | undefined {
  const parts: string[] = [];
  const sg = asStr(p.space_group);
  if (sg) parts.push(sg);
  if (asNum(p.n_unique) !== undefined) parts.push(`${fmtInt(p.n_unique)} unique`);
  if (asNum(p.r_int) !== undefined) parts.push(`R_int ${fmtFixed(p.r_int, 3)}`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

function buildItems(events: RunEvent[]): Item[] {
  const items: Item[] = [];
  const openStages = new Map<string, number>(); // stage name -> item index
  let openApprovalIdx = -1; // index of the newest unresolved approval item

  const resolveApproval = (resolution: ApprovalResolution) => {
    if (openApprovalIdx >= 0) {
      const it = items[openApprovalIdx];
      if (it.type === "approval" && !it.resolution) it.resolution = resolution;
      openApprovalIdx = -1;
    }
  };

  for (const ev of events) {
    const p = ev.payload;
    switch (ev.kind) {
      case "stage_start": {
        resolveApproval("approved");
        const stage = asStr(p.stage) ?? "stage";
        items.push({
          id: ev.event_id,
          type: "stage",
          label: stageLabel(stage),
          sub: datasetSub(p),
        });
        openStages.set(stage, items.length - 1);
        break;
      }
      case "stage_end": {
        resolveApproval("approved");
        const stage = asStr(p.stage) ?? "stage";
        const sub = stageEndSub(p);
        const openIdx = openStages.get(stage);
        if (openIdx !== undefined) {
          const open = items[openIdx];
          if (open.type === "stage" && sub && !open.sub) open.sub = sub;
          openStages.delete(stage);
        } else {
          items.push({
            id: ev.event_id,
            type: "stage",
            label: stageLabel(stage),
            sub,
          });
        }
        break;
      }
      case "tool_call": {
        resolveApproval("approved");
        const tool = asStr(p.tool) ?? "tool";
        const params =
          p.params && Object.keys(p.params).length > 0
            ? JSON.stringify(p.params)
            : undefined;
        items.push({
          id: ev.event_id,
          type: "tool",
          tool,
          label: toolLabel(tool),
          params,
        });
        break;
      }
      case "tool_result": {
        const tool = asStr(p.tool) ?? "tool";
        for (let i = items.length - 1; i >= 0; i--) {
          const it = items[i];
          if (it.type === "tool" && it.tool === tool && !it.result) {
            it.result = {
              ok: p.ok === true,
              elapsed: asNum(p.elapsed_s),
              chips: resultChips(tool, p.summary ?? {}),
              error: asStr(p.error) ?? undefined,
            };
            break;
          }
        }
        break;
      }
      case "agent_thought": {
        resolveApproval("approved");
        const text = asStr(p.text);
        if (text) {
          items.push({
            id: ev.event_id,
            type: "thought",
            step: asNum(p.step),
            text,
          });
        }
        break;
      }
      case "pending_approval": {
        resolveApproval("approved");
        const tool = asStr(p.tool) ?? "tool";
        items.push({
          id: ev.event_id,
          type: "approval",
          tool,
          label: toolLabel(tool),
          params:
            p.params && Object.keys(p.params).length > 0
              ? JSON.stringify(p.params)
              : undefined,
          rationale: asStr(p.rationale),
        });
        openApprovalIdx = items.length - 1;
        break;
      }
      case "agent_action_rejected": {
        resolveApproval("rejected");
        const comment = asStr(p.comment);
        items.push({
          id: ev.event_id,
          type: "note",
          text: `Proposed action rejected${comment ? `: "${comment}"` : ""}. The agent will reconsider.`,
        });
        break;
      }
      case "approval_timeout": {
        resolveApproval("auto-approved");
        items.push({
          id: ev.event_id,
          type: "note",
          text: "No response - action auto-approved after timeout.",
        });
        break;
      }
      case "agent_finish": {
        resolveApproval("approved");
        items.push({
          id: ev.event_id,
          type: "finish",
          status: asStr(p.status) ?? "finished",
          assessment: asStr(p.assessment),
        });
        break;
      }
      default:
        break;
    }
  }
  return items;
}

/* ---------------------------------------------------------------- rendering */

const STICK_THRESHOLD_PX = 48;

export function Timeline({
  runId,
  events,
  running,
  decisions,
  onDecide,
}: {
  runId: string;
  events: RunEvent[];
  running: boolean;
  decisions: Record<string, LocalDecision>;
  onDecide: (eventId: string, decision: LocalDecision) => void;
}) {
  const items = useMemo(() => buildItems(events), [events]);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [events.length, running]);

  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    stickRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (items.length === 0) {
    return running ? (
      <div className="flex items-center gap-2.5 px-5 py-6 text-[12px] text-zinc-400 dark:text-zinc-500">
        <Spinner className="text-indigo-500" />
        Waiting for the first events…
      </div>
    ) : (
      <EmptyState title="No activity recorded" />
    );
  }

  const lastIdx = items.length - 1;

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="h-full overflow-y-auto px-4 py-4"
    >
      <ol className="relative">
        <span
          aria-hidden="true"
          className="absolute top-1.5 bottom-1.5 left-[7px] w-px bg-zinc-200 dark:bg-zinc-800"
        />
        {items.map((item, i) => (
          <TimelineItem
            key={item.id}
            item={item}
            runId={runId}
            running={running}
            active={running && i === lastIdx}
            expanded={expanded.has(item.id)}
            onToggle={() => toggleExpanded(item.id)}
            decision={decisions[item.id]}
            onDecide={onDecide}
          />
        ))}
      </ol>
    </div>
  );
}

function Node({
  active,
  tone = "neutral",
  pulse = false,
}: {
  active: boolean;
  tone?: "neutral" | "green" | "red" | "indigo" | "amber";
  pulse?: boolean;
}) {
  return (
    <span className="absolute top-[3px] left-0 flex h-4 w-4 items-center justify-center bg-white dark:bg-zinc-950">
      {active ? (
        <Spinner className="h-3 w-3 text-indigo-500" />
      ) : (
        <StatusDot tone={tone} pulse={pulse} />
      )}
    </span>
  );
}

function ApprovalCard({
  item,
  runId,
  running,
  decision,
  expanded,
  onToggle,
  onDecide,
}: {
  item: Extract<Item, { type: "approval" }>;
  runId: string;
  running: boolean;
  decision: LocalDecision | undefined;
  expanded: boolean;
  onToggle: () => void;
  onDecide: (eventId: string, decision: LocalDecision) => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stream-inferred resolution wins; a local decision covers the gap between
  // POSTing and the engine's next events arriving.
  const resolution: ApprovalResolution | LocalDecision | undefined =
    item.resolution ?? decision;
  const open = resolution === undefined && running;

  const decide = async (approve: boolean) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await approveAction(runId, {
        event_id: item.id,
        approve,
        comment: comment.trim(),
      });
      onDecide(item.id, approve ? "approved" : "rejected");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const statusChip =
    resolution === "approved" ? (
      <Chip tone="green">Approved</Chip>
    ) : resolution === "rejected" ? (
      <Chip tone="red">Rejected</Chip>
    ) : resolution === "auto-approved" ? (
      <Chip tone="amber">Auto-approved</Chip>
    ) : !running ? (
      <Chip>No longer pending</Chip>
    ) : null;

  return (
    <div
      className={cx(
        "rounded-[10px] border p-3 transition-colors duration-200",
        open
          ? "border-indigo-300 bg-indigo-50/40 dark:border-indigo-700 dark:bg-indigo-950/20"
          : "border-zinc-200 bg-zinc-50/50 dark:border-zinc-800 dark:bg-zinc-900/40",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium tracking-[0.08em] text-indigo-600 uppercase dark:text-indigo-400">
          AI requests approval
        </span>
        {statusChip}
      </div>
      <div className="mt-1 text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
        {item.label}
      </div>
      {item.rationale && (
        <button
          type="button"
          onClick={onToggle}
          className="mt-1.5 block w-full text-left"
        >
          <span
            className={cx(
              "block text-[12px] leading-relaxed whitespace-pre-wrap text-zinc-600 dark:text-zinc-300",
              !expanded && "line-clamp-3",
            )}
          >
            {item.rationale}
          </span>
        </button>
      )}
      {item.params && (
        <div
          className="mt-1.5 font-mono text-[11px] break-all text-zinc-500 dark:text-zinc-400"
          title={item.params}
        >
          {item.params}
        </div>
      )}
      {open && (
        <div className="mt-2.5 flex flex-col gap-2">
          <input
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional comment for the agent…"
            disabled={busy}
            className="h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs text-zinc-800 placeholder:text-zinc-400 focus:border-indigo-400 focus:outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-500 dark:focus:border-indigo-500"
          />
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={busy} onClick={() => void decide(true)}>
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void decide(false)}
              className="text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
            >
              Reject
            </Button>
            {busy && <Spinner className="text-indigo-500" />}
          </div>
          {error && (
            <div className="text-[11px] text-red-600 dark:text-red-400">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TimelineItem({
  item,
  runId,
  running,
  active,
  expanded,
  onToggle,
  decision,
  onDecide,
}: {
  item: Item;
  runId: string;
  running: boolean;
  active: boolean;
  expanded: boolean;
  onToggle: () => void;
  decision: LocalDecision | undefined;
  onDecide: (eventId: string, decision: LocalDecision) => void;
}) {
  switch (item.type) {
    case "stage":
      return (
        <li className="relative pb-4 pl-7">
          <Node active={active} tone="indigo" />
          <div className="pt-px text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
            {item.label}
          </div>
          {item.sub && (
            <div className="mt-0.5 font-mono text-[11px] text-zinc-500 tabular-nums dark:text-zinc-400">
              {item.sub}
            </div>
          )}
        </li>
      );

    case "tool": {
      const r = item.result;
      const failed = r !== undefined && !r.ok;
      return (
        <li className="relative pb-4 pl-7">
          <Node
            active={active && r === undefined}
            tone={r === undefined ? "neutral" : r.ok ? "green" : "red"}
          />
          <div className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 text-[13px] text-zinc-800 dark:text-zinc-200">
              {item.label}
            </span>
            {r?.elapsed !== undefined && (
              <span className="shrink-0 font-mono text-[11px] text-zinc-400 tabular-nums dark:text-zinc-500">
                {fmtSeconds(r.elapsed)}
              </span>
            )}
            {r === undefined && !active && (
              <span className="shrink-0 text-[11px] text-zinc-300 dark:text-zinc-600">
                —
              </span>
            )}
          </div>
          {item.params && (
            <div
              className="mt-0.5 truncate font-mono text-[11px] text-zinc-400 dark:text-zinc-500"
              title={item.params}
            >
              {item.params}
            </div>
          )}
          {r === undefined && active && (
            <div className="mt-0.5 text-[11px] text-zinc-400 dark:text-zinc-500">
              running…
            </div>
          )}
          {failed && (
            <div className="mt-1">
              <Chip tone="red">failed</Chip>
              {r.error && (
                <div className="mt-1 text-[11px] break-words text-red-600 dark:text-red-400">
                  {r.error}
                </div>
              )}
            </div>
          )}
          {r && r.ok && r.chips.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {r.chips.map((c) => (
                <Chip key={c.k} className="font-mono tabular-nums">
                  <span className="text-zinc-400 dark:text-zinc-500">{c.k}</span>
                  {c.v}
                </Chip>
              ))}
            </div>
          )}
        </li>
      );
    }

    case "thought":
      return (
        <li className="relative pb-4 pl-7">
          <Node active={active} />
          <button
            type="button"
            onClick={onToggle}
            className="block w-full rounded-lg bg-zinc-50 px-3 py-2 text-left transition-colors duration-150 hover:bg-zinc-100 dark:bg-zinc-900 dark:hover:bg-zinc-800/80"
          >
            <div className="mb-1 text-[10px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
              AI reasoning{item.step !== undefined ? ` · step ${item.step}` : ""}
            </div>
            <div
              className={cx(
                "text-[12px] leading-relaxed whitespace-pre-wrap text-zinc-500 dark:text-zinc-400",
                !expanded && "line-clamp-3",
              )}
            >
              {item.text}
            </div>
          </button>
        </li>
      );

    case "approval": {
      const open = item.resolution === undefined && decision === undefined && running;
      return (
        <li className="relative pb-4 pl-7">
          <Node
            active={false}
            tone={
              open
                ? "amber"
                : item.resolution === "rejected" || decision === "rejected"
                  ? "red"
                  : item.resolution === "auto-approved"
                    ? "amber"
                    : "green"
            }
            pulse={open}
          />
          <ApprovalCard
            item={item}
            runId={runId}
            running={running}
            decision={decision}
            expanded={expanded}
            onToggle={onToggle}
            onDecide={onDecide}
          />
        </li>
      );
    }

    case "note":
      return (
        <li className="relative pb-4 pl-7">
          <Node active={false} />
          <p className="text-[12px] leading-relaxed text-zinc-400 italic dark:text-zinc-500">
            {item.text}
          </p>
        </li>
      );

    case "finish":
      return (
        <li className="relative pb-1 pl-7">
          <Node
            active={false}
            tone={item.status === "failed" ? "red" : "indigo"}
          />
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-zinc-800 dark:text-zinc-200">
              Agent finished
            </span>
            <Chip tone={item.status === "failed" ? "red" : "indigo"}>
              {item.status}
            </Chip>
          </div>
          {item.assessment && (
            <p className="mt-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              {item.assessment}
            </p>
          )}
        </li>
      );
  }
}
