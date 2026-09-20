/** Metrics tab (P2): lineage walk of the viewed node → stat rows with
 * inline-SVG sparklines (per the dataviz method: 2px round-cap line in the
 * de-emphasis ink, accent end-dot; deltas colored by direction, down = good
 * for R metrics), a compact lineage table, and thread token usage with a
 * context-window meter at the bottom. */
import { useMemo } from "react";
import { cx, fmtTokens } from "../../lib/format";
import { metricDelta } from "../../lib/metricDelta";
import { comparableMetric, signedDifference } from "../../lib/structureComparison";
import { useNodeComparison } from "../../state/useNodeComparison";
import { t } from "../../lib/i18n";
import { shelWorkingCutoff } from "../../lib/shel";
import type { RefineNode } from "../../lib/wbTypes";
import { useCrystal } from "../../state/CrystalProvider";
import { useThreadOptional } from "../../state/ThreadProvider";
import { CoordinationSection } from "./CoordinationSection";
import { lineageOf } from "./CrystalPane";

// ------------------------------------------------------------------ sparkline

function Sparkline({
  values,
  nodes,
  comparable,
  width = 104,
  height = 26,
}: {
  values: (number | null)[];
  nodes: string[];
  comparable: boolean;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true">
        <line
          x1={2}
          y1={height / 2}
          x2={width - 2}
          y2={height / 2}
          stroke="var(--color-line)"
          strokeWidth={2}
          strokeLinecap="round"
        />
      </svg>
    );
  }
  const finite = values.filter((value): value is number => value !== null && Number.isFinite(value));
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const span = max - min || 1;
  const padX = 4;
  const padY = 5;
  const step = (width - padX * 2) / (values.length - 1);
  const pts = values.map((v, i) => {
    if (v === null || !Number.isFinite(v)) return null;
    const x = padX + i * step;
    const y = padY + (1 - (v - min) / span) * (height - padY * 2);
    return [x, y] as const;
  });
  const previous = pts.at(-2);
  const last = pts.at(-1);
  return (
    <svg width={width} height={height} role="img" aria-label={t.crystal.mtSparklineAria}>
      {comparable && previous && last && <line x1={previous[0]} y1={previous[1]} x2={last[0]} y2={last[1]}
        stroke="var(--color-ink-3)" strokeWidth={2} />}
      {pts.map((point, index) => point && <circle key={nodes[index] ?? index} cx={point[0]} cy={point[1]}
        r={index === pts.length - 1 ? 3.5 : 2} fill={index === pts.length - 1 ? "var(--color-accent)" : "var(--color-ink-3)"}>
        <title>{nodes[index]} · {values[index]}</title>
      </circle>)}
    </svg>
  );
}

function MetricRow({
  label,
  values,
  digits,
  unit,
  ideal,
  neutralDelta = false,
  comparable = false,
  nodes,
}: {
  label: string;
  values: (number | null)[];
  nodes: string[];
  comparable?: boolean;
  digits: number;
  unit?: string;
  ideal?: number;
  /** direction has no good/bad meaning (e.g. 参数) - delta stays gray */
  neutralDelta?: boolean;
}) {
  const cur = values.at(-1);
  const prev = values.at(-2);
  const { changed, improved, worsened, direction } = metricDelta(
    cur,
    prev,
    digits,
    ideal,
    false,
    comparable,
  );
  return (
    <div className="flex items-center gap-2.5 px-3 py-1.5">
      <span className="w-9 shrink-0 text-2xs font-medium text-ink-3">
        {label}
      </span>
      <span className="font-mono text-sm font-semibold text-ink tabular-nums">
        {cur != null ? cur.toFixed(digits) : "—"}
        {unit !== undefined && cur != null && (
          <span className="ml-0.5 text-2xs font-normal text-ink-3">{unit}</span>
        )}
      </span>
      {changed && (
        <span
          className={cx(
            "font-mono text-2xs tabular-nums",
            neutralDelta
              ? "text-ink-3"
              : improved
                ? "text-ok"
                : worsened
                  ? "text-danger"
                  : "text-ink-3",
          )}
        >
          {direction === "down" ? "▼" : direction === "up" ? "▲" : ""}
          {direction ? Math.abs((cur as number) - (prev as number)).toFixed(digits) : signedDifference(cur, prev, digits)}
        </span>
      )}
      <span className="ml-auto shrink-0">
        <Sparkline values={values} nodes={nodes} comparable={comparable} />
      </span>
    </div>
  );
}

// -------------------------------------------------------------- lineage table

function LineageTable({
  lineage,
  viewNode,
  onView,
}: {
  lineage: RefineNode[];
  viewNode: string | null;
  onView: (id: string) => void;
}) {
  const f = (v: number | null, d: number): string =>
    v === null ? "—" : v.toFixed(d);
  return (
    <div className="px-3">
      <table className="w-full border-collapse font-mono text-2xs tabular-nums">
        <thead>
          <tr className="text-left text-ink-3">
            <th className="py-1 pr-2 font-medium">{t.nodeLabel}</th>
            <th className="py-1 pr-2 font-medium">{t.crystal.mtToolCol}</th>
            <th className="py-1 pr-2 text-right font-medium">R1</th>
            <th className="py-1 pr-2 text-right font-medium">wR2</th>
            <th className="py-1 pr-2 text-right font-medium">GooF</th>
            <th className="py-1 text-right font-medium">{t.atomsLabel}</th>
          </tr>
        </thead>
        <tbody>
          {lineage.map((n) => (
            <tr
              key={n.id}
              tabIndex={0}
              aria-label={t.crystal.viewNodeAria(n.id)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onView(n.id); } }}
              onClick={() => onView(n.id)}
              title={n.metrics_current ? undefined : t.staleMetricsTip}
              className={cx(
                "cursor-pointer border-t border-line/60 transition-colors",
                n.id === viewNode
                  ? "bg-raised/70 text-ink"
                  : "text-ink-2 hover:bg-raised/40",
                !n.metrics_current && "text-ink-3",
              )}
            >
              <td className="py-1 pr-2">{n.id}</td>
              <td className="max-w-24 truncate py-1 pr-2" title={n.tool}>
                {n.tool}
              </td>
              <td
                className={cx(
                  "py-1 pr-2 text-right",
                  !n.metrics_current && "opacity-60",
                )}
              >
                {f(n.r1, 4)}
              </td>
              <td
                className={cx(
                  "py-1 pr-2 text-right",
                  !n.metrics_current && "opacity-60",
                )}
              >
                {f(n.wr2, 4)}
              </td>
              <td
                className={cx(
                  "py-1 pr-2 text-right",
                  !n.metrics_current && "opacity-60",
                )}
              >
                {f(n.goof, 2)}
              </td>
              <td className="py-1 text-right">{n.n_atoms}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- token usage

function UsageSection() {
  const thread = useThreadOptional();
  const usage = thread?.state.usage ?? null;
  if (!usage?.total) {
    return <div className="px-3 py-2 text-2xs text-ink-3">{t.noUsage}</div>;
  }
  const total = usage.total;
  const window_ = usage.contextWindow;
  // context bar tracks the LAST request (current context occupancy);
  // the number row above stays cumulative (session spend). A visible
  // drop in the bar after long turns = codex auto-compaction at work.
  const cur = usage.last ?? usage.total;
  const used = cur.input_tokens + cur.output_tokens;
  const pct =
    window_ !== null && window_ > 0
      ? Math.min(100, (used / window_) * 100)
      : null;
  const meterTone =
    pct !== null && pct > 90
      ? "bg-danger"
      : pct !== null && pct > 75
        ? "bg-warn"
        : "bg-accent";
  return (
    <div className="px-3 py-2">
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-2xs text-ink-2 tabular-nums">
        <span>
          {t.usageInput} {fmtTokens(total.input_tokens)}
        </span>
        <span>
          {t.usageCached} {fmtTokens(total.cached_input_tokens)}
        </span>
        <span>
          {t.usageOutput} {fmtTokens(total.output_tokens)}
        </span>
      </div>
      {pct !== null && (
        <div className="mt-2">
          <div className="flex items-baseline justify-between font-mono text-2xs text-ink-3 tabular-nums">
            <span>
              {t.contextWindow} {fmtTokens(used)} /{" "}
              {fmtTokens(window_ as number)}
            </span>
            <span>
              {pct.toFixed(0)}% {t.contextUsedSuffix}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-pill bg-raised">
            <div
              className={cx("h-full rounded-pill", meterTone)}
              style={{ width: `${Math.max(1, pct)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------- tab

/** The data side of the picture.
 *
 * Rint bounds what R1 can be, and it was previously visible only as a
 * chip in a chat message that scrolled away - so a session could argue
 * about a "high" R1 with no reminder that the merge residual was 0.57.
 * These numbers move only when the data move, so they are a static block,
 * not a trend. */
function DataSection({ node }: { node: RefineNode | undefined }) {
  const d = node?.data;
  if (!d) return null;
  const cells: Array<[string, string]> = [];
  if (d.r_int !== undefined) cells.push(["Rint", d.r_int.toFixed(4)]);
  if (d.completeness !== undefined) {
    cells.push([t.dataCompleteness, `${(d.completeness * 100).toFixed(1)}%`]);
  }
  // d_min is what the data nominally reach; a SHEL card narrows the working
  // range, and the two were shown side by side without saying which is which
  // (round-3 visual review, item 6)
  if (d.d_min !== undefined) {
    cells.push([t.dataDminNominal, `${d.d_min.toFixed(2)} Å`]);
  }
  const shelHi = shelWorkingCutoff(d.shel);
  if (shelHi !== null)
    cells.push([t.dataDminWorking, `${shelHi.toFixed(2)} Å`]);
  if (d.n_unique !== undefined) {
    cells.push([t.dataUnique, d.n_unique.toLocaleString()]);
  }
  if (d.n_obs !== undefined && d.n_unique) {
    cells.push([t.dataRedundancy, (d.n_obs / d.n_unique).toFixed(1)]);
  }
  if (d.space_group) cells.push([t.dataSpaceGroup, d.space_group]);
  if (cells.length === 0) return null;
  return (
    <div className="mt-1.5 shrink-0 border-t border-line pt-1.5">
      <div className="flex items-baseline gap-2 px-3 pt-1 pb-1">
        <span className="text-2xs font-medium text-ink-3">
          {t.dataSectionTitle}
        </span>
        {d.hklf === 5 && (
          <span className="rounded-sm bg-warn/10 px-1 text-2xs text-warn">
            HKLF5
          </span>
        )}
        {d.shel && (
          <span
            className="rounded-sm bg-raised px-1 font-mono text-2xs text-ink-3"
            title={t.dataShelTip}
          >
            {d.shel}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 px-3 pb-1">
        {cells.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between">
            <span className="text-2xs text-ink-3">{k}</span>
            <span className="font-mono text-2xs tabular-nums">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MetricsPanel() {
  const { state, viewNode: onView, project } = useCrystal();
  const lineage = useMemo(
    () => lineageOf(state.nodes, state.viewNode),
    [state.nodes, state.viewNode],
  );
  const viewed = lineage.at(-1);

  // Trend series over ACTUAL refinements only - edit nodes inherit the parent
  // metrics and would draw fake flat segments / fake "current" values.
  const refined = useMemo(
    () => lineage.filter((n) => n.metrics_current),
    [lineage],
  );
  const pairInfo = useNodeComparison(project, refined.at(-1), refined.at(-2));
  const canCompare = (metric: "r1" | "wr2" | "goof") => comparableMetric(pairInfo.data, metric, refined.at(-1), refined.at(-2));
  const nodeIds = refined.map((node) => node.id);
  const series = (pick: (n: RefineNode) => number | null): (number | null)[] =>
    refined.map((node) => { const value = pick(node); return value !== null && Number.isFinite(value) ? value : null; });

  const r1 = series((n) => n.r1);
  const wr2 = series((n) => n.wr2);
  const goof = series((n) => n.goof);
  const peak = series((n) => n.diff_map_max);
  // n_params < 0 is the "not reported" placeholder from older job parsers;
  // the panel used to print "参数 -1" verbatim
  const nParams = series((n) =>
    n.n_params !== null && n.n_params >= 0 ? n.n_params : null,
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="metrics-panel">
      <div className="shrink-0 pt-1.5">
        <div className="flex items-baseline gap-2 px-3 pt-1 pb-0.5">
          <span className="text-2xs font-medium text-ink-3">
            {t.metricsTrend}
          </span>
          {viewed !== undefined && (
            <span className="font-mono text-2xs text-ink-3">{viewed.id}</span>
          )}
          {viewed !== undefined && !viewed.metrics_current && (
            <span
              className="rounded-sm bg-warn/10 px-1 text-2xs text-warn"
              title={t.staleMetricsTip}
            >
              {t.staleMetrics}
            </span>
          )}
        </div>
        <MetricRow label="R1" values={r1} nodes={nodeIds} digits={4} comparable={canCompare("r1")} />
        <MetricRow label="wR2" values={wr2} nodes={nodeIds} digits={4} comparable={canCompare("wr2")} />
        <MetricRow label="GooF" values={goof} nodes={nodeIds} digits={2} ideal={1} comparable={canCompare("goof")} />
        <MetricRow label={t.peakLabel} values={peak} nodes={nodeIds} digits={2} unit="eÅ⁻³" />
        <MetricRow
          label={t.paramsLabel}
          values={nParams}
          nodes={nodeIds}
          digits={0}
          neutralDelta
        />
      </div>
      <DataSection node={viewed} />
      <div className="mt-1.5 shrink-0 border-t border-line pt-1.5">
        <CoordinationSection />
      </div>
      <div className="mt-1.5 shrink-0 border-t border-line pt-1.5">
        <div className="px-3 pt-1 pb-1 text-2xs font-medium text-ink-3">
          {t.lineageTitle}
        </div>
        <LineageTable
          lineage={lineage}
          viewNode={state.viewNode}
          onView={onView}
        />
      </div>
      <div className="mt-auto shrink-0 border-t border-line pt-0.5 pb-1.5">
        <div className="px-3 pt-1.5 pb-0.5 text-2xs font-medium text-ink-3">
          {t.usageTitle}
        </div>
        <UsageSection />
      </div>
    </div>
  );
}
