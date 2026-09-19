import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router-dom";
import type { RunStatus } from "../../lib/api";
import { useRun } from "../hooks/useRun";
import { useEvents } from "../hooks/useEvents";
import { deriveMetrics } from "../../lib/derive";
import { cx, fmtCell, fmtFixed } from "../../lib/format";
import { OverviewTab } from "../components/OverviewTab";
import { ReportTab } from "../components/ReportTab";
import { Timeline, type LocalDecision } from "../components/Timeline";
import {
  Card,
  Chip,
  ConfidenceBadge,
  EmptyState,
  SectionLabel,
  Spinner,
  StatusDot,
  Tabs,
} from "../../components/ui";

const StructureViewer = lazy(() => import("../../components/StructureViewer"));

type TabId = "overview" | "structure" | "report";

function StatusChip({ status }: { status: RunStatus | null }) {
  switch (status) {
    case "running":
      return (
        <Chip tone="indigo">
          <StatusDot tone="indigo" pulse />
          Running
        </Chip>
      );
    case "done":
      return (
        <Chip tone="green">
          <StatusDot tone="green" />
          Done
        </Chip>
      );
    case "failed":
      return (
        <Chip tone="red">
          <StatusDot tone="red" />
          Failed
        </Chip>
      );
    default:
      return <Chip>…</Chip>;
  }
}

function HeaderMetric({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
        {label}
      </span>
      <span className="font-mono text-[13px] tabular-nums text-zinc-800 dark:text-zinc-200">
        {children}
      </span>
    </div>
  );
}

export default function RunView() {
  const { id = "" } = useParams();
  const { run, error: runError } = useRun(id);
  const status: RunStatus | null = run?.status ?? null;
  const events = useEvents(id, status);
  const metrics = useMemo(() => deriveMetrics(run, events), [run, events]);
  const [tab, setTab] = useState<TabId>("overview");
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [decisions, setDecisions] = useState<Record<string, LocalDecision>>({});
  const running = status === "running";

  useEffect(() => {
    setDecisions({});
    setTab("overview");
  }, [id]);

  const onDecide = useCallback((eventId: string, decision: LocalDecision) => {
    setDecisions((prev) => ({ ...prev, [eventId]: decision }));
  }, []);

  const lastEvent = events.at(-1);
  const awaitingReview =
    running &&
    lastEvent?.kind === "pending_approval" &&
    decisions[lastEvent.event_id] === undefined;

  if (runError !== null && run === null) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <Card className="max-w-md px-6 py-8 text-center">
          <div className="text-[14px] font-medium">Run not found</div>
          <p className="mt-2 text-[12px] text-zinc-500 dark:text-zinc-400">
            {runError}
          </p>
          <Link
            to="/legacy"
            className="mt-4 inline-block text-[13px] font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
          >
            Back to home
          </Link>
        </Card>
      </div>
    );
  }

  const cell = fmtCell(metrics.cell);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-zinc-200 px-6 py-3 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <h1 className="font-mono text-[13px] font-medium">{id}</h1>
          <StatusChip status={status} />
          {awaitingReview && (
            <Chip tone="amber">
              <StatusDot tone="amber" pulse />
              Waiting for your review
            </Chip>
          )}
        </div>
        <span
          className="hidden h-4 w-px bg-zinc-200 sm:block dark:bg-zinc-800"
          aria-hidden="true"
        />
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
          {metrics.spaceGroup && (
            <HeaderMetric label="Space group">{metrics.spaceGroup}</HeaderMetric>
          )}
          {cell && <HeaderMetric label="Cell">{cell}</HeaderMetric>}
          {metrics.r1 !== undefined && (
            <HeaderMetric label="R1">{fmtFixed(metrics.r1, 4)}</HeaderMetric>
          )}
          {metrics.wr2 !== undefined && (
            <HeaderMetric label="wR2">{fmtFixed(metrics.wr2, 4)}</HeaderMetric>
          )}
          {metrics.goof !== undefined && (
            <HeaderMetric label="GooF">{fmtFixed(metrics.goof, 3)}</HeaderMetric>
          )}
          {metrics.confidence && (
            <div className="flex items-baseline gap-1.5">
              <span className="text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
                Confidence
              </span>
              <ConfidenceBadge
                score={metrics.confidence.score}
                grade={metrics.confidence.grade}
              />
            </div>
          )}
        </div>
      </div>

      {/* Stacks vertically below 900px (timeline on top, collapsible with a
          capped height); two fixed columns from 900px up. */}
      <div className="flex min-h-0 flex-1 flex-col min-[900px]:flex-row">
        <aside
          className={cx(
            "flex w-full shrink-0 flex-col border-b border-zinc-200 dark:border-zinc-800",
            "min-[900px]:w-[340px] min-[900px]:border-r min-[900px]:border-b-0",
            timelineOpen && "max-h-[40dvh] min-[900px]:max-h-none",
          )}
        >
          <div className="flex shrink-0 items-center gap-2 border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
            <SectionLabel>Activity</SectionLabel>
            {running && <Spinner className="h-3 w-3 text-indigo-500" />}
            <button
              type="button"
              onClick={() => setTimelineOpen((o) => !o)}
              aria-expanded={timelineOpen}
              aria-label={timelineOpen ? "Collapse timeline" : "Expand timeline"}
              className="ml-auto flex h-6 w-6 items-center justify-center rounded-md text-zinc-400 transition-colors duration-150 hover:bg-zinc-100 hover:text-zinc-700 min-[900px]:hidden dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              <svg
                viewBox="0 0 24 24"
                className={cx(
                  "h-3.5 w-3.5 transition-transform duration-200",
                  !timelineOpen && "-rotate-90",
                )}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
          </div>
          <div
            className={cx(
              "min-h-0 flex-1",
              !timelineOpen && "hidden min-[900px]:block",
            )}
          >
            {/* While the run detail is still loading, show the waiting state
                rather than "no activity". */}
            <Timeline
              runId={id}
              events={events}
              running={running || status === null}
              decisions={decisions}
              onDecide={onDecide}
            />
          </div>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {status === "failed" && run?.error && (
            <div className="mx-6 mt-4 max-h-44 overflow-y-auto rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/40">
              <div className="mb-1 text-[11px] font-medium tracking-[0.08em] text-red-700 uppercase dark:text-red-400">
                Run failed
              </div>
              <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap text-red-700 dark:text-red-400">
                {run.error}
              </pre>
            </div>
          )}
          <div className="px-6 pt-4">
            <Tabs<TabId>
              tabs={[
                { id: "overview", label: "Overview" },
                { id: "structure", label: "Structure" },
                { id: "report", label: "Report" },
              ]}
              value={tab}
              onChange={setTab}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {run === null ? (
              <div className="flex items-center gap-2.5 py-8 text-[13px] text-zinc-400">
                <Spinner className="text-indigo-500" />
                Loading run…
              </div>
            ) : tab === "overview" ? (
              <OverviewTab run={run} events={events} />
            ) : tab === "structure" ? (
              run.has_cif ? (
                <div className="h-full min-h-[420px]">
                  <Suspense
                    fallback={
                      <div className="flex h-full items-center justify-center gap-2.5 text-[13px] text-zinc-400">
                        <Spinner className="text-indigo-500" />
                        Loading 3D viewer…
                      </div>
                    }
                  >
                    <StructureViewer runId={id} />
                  </Suspense>
                </div>
              ) : (
                <EmptyState title="No structure model yet">
                  {running
                    ? "The 3D structure will appear once a model has been written."
                    : "This run did not produce a CIF."}
                </EmptyState>
              )
            ) : (
              <ReportTab run={run} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
