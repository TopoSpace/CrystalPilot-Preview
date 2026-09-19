/** The whole board at a glance: one card per known project with its live
 * state, refinement head and validation standing.
 *
 * The recent-projects grid it replaces was pure navigation - you could
 * not tell which project was running, how far any of them had got, or
 * which one had unresolved A-level alerts, without opening each in turn
 * (and opening one closed the last). /api/projects/status reads all of
 * it off disk, so this costs no engine. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { projectsStatus } from "../lib/wbApi";
import type { ProjectStatus } from "../lib/wbTypes";
import { zh } from "../lib/zh";
import { useWorkbench } from "../state/WorkbenchProvider";
import { IconFolder } from "./icons";
import { projectHomeUrl, projectLabel, RECENT_PROJECTS_LIMIT } from "./urls";

function relTime(ts: number | null | undefined): string | null {
  if (!ts) return null;
  const mins = Math.round((Date.now() / 1000 - ts) / 60);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.round(h / 24)} 天前`;
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "danger";
}) {
  const color =
    tone === "danger"
      ? "text-danger"
      : tone === "warn"
        ? "text-warn"
        : tone === "ok"
          ? "text-ok"
          : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-2xs text-ink-3">{label}</div>
      <div className={`truncate text-sm tabular-nums ${color}`}>
        {value}
      </div>
    </div>
  );
}

function StatusCard({ p }: { p: ProjectStatus }) {
  const wb = useWorkbench();
  const navigate = useNavigate();
  const alertsA = p.checkcif?.A ?? null;
  const r1 = p.r1 ?? p.r1_best ?? null;
  const when = relTime(p.last_active ?? p.opened);

  return (
    <button
      type="button"
      title={p.path}
      onClick={() => {
        void wb.openProject(p.path).then((ok) => {
          if (ok) navigate(projectHomeUrl(p.path));
        });
      }}
      className="flex w-full flex-col gap-2 rounded-card border border-line
                 bg-surface px-3.5 py-3 text-left transition-colors
                 hover:bg-raised"
    >
      <div className="flex items-center gap-2">
        {p.busy ? (
          <span
            className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-ok"
            aria-hidden
          />
        ) : (
          <IconFolder size={15} className="shrink-0 text-ink-3" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {projectLabel(p.path, p.display_name)}
        </span>
        <span className="shrink-0 text-2xs text-ink-3">
          {p.busy ? zh.running : when}
        </span>
      </div>

      {p.n_nodes ? (
        <div className="grid grid-cols-4 gap-2">
          {/* R1 is deliberately NOT colour-graded: what counts as a good
              R1 depends on the crystal (disordered MOF solvent, weak
              high-angle data), and a green/plain split at some cutoff
              would put a verdict on a number that needs context */}
          <Metric label="R1" value={r1 === null ? "—" : r1.toFixed(4)} />
          <Metric label={zh.statusNodes} value={String(p.n_nodes)} />
          <Metric
            label={zh.statusAlertsA}
            value={alertsA === null ? "—" : String(alertsA)}
            tone={alertsA ? "danger" : alertsA === 0 ? "ok" : undefined}
          />
          <Metric
            label={zh.statusDeliveries}
            value={String(p.n_deliveries ?? 0)}
          />
        </div>
      ) : (
        <div className="text-2xs text-ink-3">{zh.statusNoWork}</div>
      )}

      {p.last_title && (
        <div className="truncate text-2xs text-ink-3">{p.last_title}</div>
      )}
    </button>
  );
}

export function ProjectStatusBoard() {
  const [rows, setRows] = useState<ProjectStatus[] | null>(null);
  const wb = useWorkbench();

  const load = useCallback(() => {
    void projectsStatus()
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  useEffect(() => {
    load();
    // a running project's numbers move; the endpoint is disk-only so a
    // slow poll is cheap, and this view is not open during long work
    const t = window.setInterval(load, 20_000);
    return () => window.clearInterval(t);
  }, [load, wb.recent.length]);

  if (rows === null || rows.length === 0) return null;

  return (
    <div className="mt-10 text-left">
      <div className="flex items-center gap-2 px-1">
        <span className="text-xs font-medium text-ink-3">
          {zh.statusBoard}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            load();
          }}
          className="ml-auto text-2xs text-ink-3 transition-colors hover:text-ink-2"
        >
          {zh.statusRefresh}
        </button>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {rows.slice(0, RECENT_PROJECTS_LIMIT).map((p) => (
          <StatusCard key={p.path} p={p} />
        ))}
      </div>
    </div>
  );
}
