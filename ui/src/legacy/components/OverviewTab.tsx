import { useMemo, type ReactNode } from "react";
import type { RunDetail, RunEvent, ValidationAlert } from "../../lib/api";
import {
  deriveAgentFinish,
  deriveAlerts,
  deriveTrajectory,
} from "../../lib/derive";
import { fmtFixed, fmtInt } from "../../lib/format";
import { Card, Chip, SectionLabel, StatusDot, type ChipTone } from "../../components/ui";

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}) {
  return (
    <Card className="px-4 py-3.5">
      <SectionLabel>{label}</SectionLabel>
      <div className="mt-1.5 font-mono text-[22px] leading-none font-semibold tracking-tight tabular-nums">
        {value}
      </div>
      {sub && (
        <div className="mt-1.5 text-[11px] text-zinc-400 dark:text-zinc-500">
          {sub}
        </div>
      )}
    </Card>
  );
}

function severityTone(severity: string): ChipTone {
  switch (severity) {
    case "error":
      return "red";
    case "warning":
      return "amber";
    default:
      return "neutral";
  }
}

function severityDot(severity: string): "red" | "amber" | "neutral" {
  switch (severity) {
    case "error":
      return "red";
    case "warning":
      return "amber";
    default:
      return "neutral";
  }
}

interface DedupedAlert {
  alert: ValidationAlert;
  count: number;
}

function dedupeAlerts(alerts: ValidationAlert[]): DedupedAlert[] {
  const map = new Map<string, DedupedAlert>();
  for (const a of alerts) {
    const key = `${a.severity}|${a.code}|${a.message}`;
    const existing = map.get(key);
    if (existing) existing.count += 1;
    else map.set(key, { alert: a, count: 1 });
  }
  return [...map.values()];
}

export function OverviewTab({
  run,
  events,
}: {
  run: RunDetail;
  events: RunEvent[];
}) {
  const report = run.report;
  const refinement = report?.refinement;
  const symmetry = report?.symmetry;
  const validation = report?.validation;

  const alerts = useMemo(() => deriveAlerts(run, events), [run, events]);
  const deduped = useMemo(
    () => (alerts ? dedupeAlerts(alerts) : null),
    [alerts],
  );
  const finish = useMemo(() => deriveAgentFinish(events), [events]);
  const trajectory = useMemo(() => deriveTrajectory(events), [events]);

  const running = run.status === "running";
  const dim = validation?.framework_dimensionality;

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          <MetricCard
            label="R1 (strong)"
            value={fmtFixed(refinement?.r1_strong, 4)}
            sub={
              refinement?.r1_all !== undefined
                ? `all reflections ${fmtFixed(refinement.r1_all, 4)}`
                : running
                  ? "refinement in progress"
                  : undefined
            }
          />
          <MetricCard
            label="wR2"
            value={fmtFixed(refinement?.wr2, 4)}
            sub={
              refinement?.n_params !== undefined
                ? `${fmtInt(refinement.n_params)} parameters`
                : undefined
            }
          />
          <MetricCard
            label="GooF"
            value={fmtFixed(refinement?.goof, 3)}
            sub={refinement?.mode ? `${refinement.mode} refinement` : undefined}
          />
          <MetricCard
            label="Residual density"
            value={
              refinement?.diff_map_max !== undefined ? (
                <>
                  {fmtFixed(refinement.diff_map_max, 2)}
                  <span className="text-zinc-300 dark:text-zinc-600"> / </span>
                  {fmtFixed(refinement.diff_map_min, 2)}
                </>
              ) : (
                "—"
              )
            }
            sub="max / min, e Å⁻³"
          />
          <MetricCard
            label="Reflections"
            value={fmtInt(symmetry?.n_unique)}
            sub={
              symmetry
                ? `R_int ${fmtFixed(symmetry.r_int, 3)} · completeness ${
                    symmetry.completeness !== undefined
                      ? `${(symmetry.completeness * 100).toFixed(1)}%`
                      : "—"
                  }`
                : undefined
            }
          />
          <MetricCard
            label="Framework"
            value={dim !== undefined && dim !== null ? `${dim}D` : "—"}
            sub={
              validation?.largest_fragment?.n_atoms !== undefined
                ? `largest fragment ${fmtInt(validation.largest_fragment.n_atoms)} atoms`
                : undefined
            }
          />
        </div>
      </section>

      <section>
        <Card>
          <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
            <SectionLabel>Validation alerts</SectionLabel>
            {deduped && deduped.length > 0 && (
              <Chip className="font-mono tabular-nums">
                {alerts ? alerts.length : 0}
              </Chip>
            )}
          </div>
          {deduped === null && (
            <div className="px-4 py-5 text-[12px] text-zinc-400 dark:text-zinc-500">
              {running
                ? "Validation has not run yet."
                : "No validation results available."}
            </div>
          )}
          {deduped !== null && deduped.length === 0 && (
            <div className="flex items-center gap-2 px-4 py-5 text-[12px] text-emerald-700 dark:text-emerald-400">
              <StatusDot tone="green" />
              No validation alerts.
            </div>
          )}
          {deduped !== null && deduped.length > 0 && (
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {deduped.map(({ alert, count }, i) => (
                <li key={i} className="flex items-start gap-2.5 px-4 py-2.5">
                  <span className="mt-1.5">
                    <StatusDot tone={severityDot(alert.severity)} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Chip tone={severityTone(alert.severity)}>
                        {alert.code}
                      </Chip>
                      {count > 1 && (
                        <span className="text-[11px] text-zinc-400 tabular-nums dark:text-zinc-500">
                          ×{count}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-[12px] leading-relaxed break-words text-zinc-600 dark:text-zinc-300">
                      {alert.message}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>

      {finish?.assessment && (
        <section>
          <Card>
            <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
              <SectionLabel>AI assessment</SectionLabel>
              {finish.status && (
                <Chip tone={finish.status === "failed" ? "red" : "indigo"}>
                  {finish.status}
                </Chip>
              )}
            </div>
            <p className="px-4 py-4 text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
              {finish.assessment}
            </p>
          </Card>
        </section>
      )}

      {trajectory.snapshots > 0 && (
        <p className="flex items-center gap-2 text-[12px] text-zinc-400 dark:text-zinc-500">
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M6 3v12M6 15a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V9" />
            <circle cx="6" cy="19.5" r="1.5" />
            <circle cx="18" cy="5.5" r="1.5" />
          </svg>
          The agent branched its trajectory during this run:{" "}
          {trajectory.snapshots} snapshot{trajectory.snapshots === 1 ? "" : "s"}
          {trajectory.restores > 0 &&
            `, ${trajectory.restores} restore${trajectory.restores === 1 ? "" : "s"}`}
          .
        </p>
      )}
    </div>
  );
}
