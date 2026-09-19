import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRuns, type RunListEntry } from "../../lib/api";
import { fmtFixed, timeAgo } from "../../lib/format";
import { Card, Chip, EmptyState, SectionLabel, StatusDot } from "../../components/ui";

const REFRESH_MS = 8000;
const MAX_SHOWN = 12;

function dotTone(run: RunListEntry): {
  tone: "green" | "red" | "indigo" | "neutral";
  pulse: boolean;
} {
  if (run.status === "running") return { tone: "indigo", pulse: true };
  if (run.status === "failed" || run.summary?.ok === false) {
    return { tone: "red", pulse: false };
  }
  if (run.status === "done") return { tone: "green", pulse: false };
  return { tone: "neutral", pulse: false };
}

function confidenceChip(score: number | null | undefined) {
  if (score == null) return <span className="text-xs text-zinc-300 dark:text-zinc-600">—</span>;
  const tone = score >= 75 ? "green" : score >= 50 ? "amber" : "red";
  return (
    <Chip tone={tone} className="font-mono tabular-nums">
      {score.toFixed(0)}/100
    </Chip>
  );
}

export function RecentRuns() {
  const [runs, setRuns] = useState<RunListEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await fetchRuns();
        if (!cancelled) {
          setRuns(list);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section>
      <SectionLabel className="mb-3">Recent runs</SectionLabel>
      <Card className="p-1.5">
        {runs === null && !error && (
          <EmptyState title="Loading runs…" />
        )}
        {error && runs === null && (
          <EmptyState title="Could not reach the CrystalPilot server">
            {error}
          </EmptyState>
        )}
        {runs !== null && runs.length === 0 && (
          <EmptyState title="No runs yet">
            Drop a dataset above to solve your first structure.
          </EmptyState>
        )}
        {runs !== null &&
          runs.slice(0, MAX_SHOWN).map((r) => {
            const d = dotTone(r);
            return (
              <Link
                key={r.run_id}
                to={`/legacy/runs/${r.run_id}`}
                className="flex items-center gap-4 rounded-lg px-3 py-2.5 transition-colors duration-150 hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
              >
                <StatusDot tone={d.tone} pulse={d.pulse} />
                <span className="w-32 shrink-0 truncate font-mono text-[13px] text-zinc-800 dark:text-zinc-200">
                  {r.run_id}
                </span>
                <span className="hidden w-24 shrink-0 truncate font-mono text-xs text-zinc-500 sm:block dark:text-zinc-400">
                  {r.summary?.space_group ?? "—"}
                </span>
                <span className="hidden shrink-0 font-mono text-xs text-zinc-500 tabular-nums sm:block dark:text-zinc-400">
                  R1&nbsp;{fmtFixed(r.summary?.r1, 4)}
                </span>
                <span className="hidden sm:block">
                  {confidenceChip(r.summary?.confidence)}
                </span>
                <span className="ml-auto shrink-0 text-xs text-zinc-400 dark:text-zinc-500">
                  {timeAgo(r.mtime)}
                </span>
              </Link>
            );
          })}
      </Card>
    </section>
  );
}
