/** Node tree (round-3 R2-B): a git-style graph that folds.
 *
 * Newest first, one lane per concurrently open branch (lib/nodeTree.ts
 * packs them, so a project with 28 branches is not 28 columns wide), a
 * header row above every branch that folds its nodes away, and the diag/*
 * family - the throw-away candidates the batch tools leave behind - behind
 * one row, collapsed by default. Each node row says where its R1 comes from
 * (its own refinement, or 沿用 nXXXX for the ancestor that earned it) and
 * carries the three marks a reader looks for: 当前查看 (the row is lit),
 * 已交付 (a write_outputs manifest names it) and R1 最优 (the best refined
 * node outside diag/*). Click a row to view that node; 检出 prefills the
 * composer with an agent-mediated checkout request (no direct mutation).
 *
 * 分支对比 (the best-of-N table, one row per branch head) stays, folded by
 * default and without the diagnostic branches. */
import { useMemo, useState, type ReactNode } from "react";
import { deliveryStatusLabel, deliveryTone } from "../../lib/delivery";
import { cx } from "../../lib/format";
import {
  bestNodeId,
  branchOfRow,
  deliveriesByNode,
  forks,
  isDiagBranch,
  isFolded,
  metricsView,
  packLanes,
  treeRows,
  type FoldState,
  type Lanes,
  type TreeRow,
} from "../../lib/nodeTree";
import { useTheme } from "../../lib/theme";
import { t } from "../../lib/i18n";
import type { DeliveryMark, RefineNode } from "../../lib/wbTypes";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useCrystal } from "../../state/CrystalProvider";
import { IconChevronRight } from "../icons";
import { useSection } from "./useSection";

const NODE_H = 44;
const HEAD_H = 28;
const COL_W = 14;
const PAD_L = 12;

/** Categorical lane palettes (adjacent pairs distinct under CVD). Colour
 * follows the LANE, not the branch, so neighbouring columns never share. */
const LANE_COLORS_LIGHT = ["#0d78f2", "#b45309", "#9333ea", "#059669", "#be185d", "#0e7490"];
const LANE_COLORS_DARK = ["#3b82f6", "#d97706", "#a855f7", "#10b981", "#ec4899", "#22d3ee"];

function laneColor(lane: number, dark: boolean): string {
  const p = dark ? LANE_COLORS_DARK : LANE_COLORS_LIGHT;
  return p[lane % p.length];
}

interface Layout {
  rows: TreeRow[];
  tops: number[];
  height: number;
  lanes: Lanes;
  width: number;
}

const rowH = (r: TreeRow): number => (r.kind === "node" ? NODE_H : HEAD_H);
const laneX = (l: number): number => PAD_L + l * COL_W;

function layout(nodes: RefineNode[], folds: FoldState): Layout {
  const rows = treeRows(nodes, folds);
  const tops: number[] = [];
  let y = 0;
  for (const r of rows) {
    tops.push(y);
    y += rowH(r);
  }
  const lanes = packLanes(rows, nodes);
  const width = PAD_L * 2 + Math.max(0, lanes.count - 1) * COL_W;
  return { rows, tops, height: y, lanes, width };
}

function GraphSvg({
  lay,
  nodes,
  activeNode,
  viewNode,
  dark,
}: {
  lay: Layout;
  nodes: RefineNode[];
  activeNode: string | null;
  viewNode: string | null;
  dark: boolean;
}) {
  const { rows, tops, height, lanes, width } = lay;
  const cy = (i: number): number => tops[i] + rowH(rows[i]) / 2;
  const first = new Map<string, number>();
  const last = new Map<string, number>();
  rows.forEach((r, i) => {
    const b = branchOfRow(r);
    if (b === null) return;
    if (!first.has(b)) first.set(b, i);
    last.set(b, i);
  });
  const paths: ReactNode[] = [];
  for (const [b, l] of lanes.lane) {
    const top = first.get(b);
    const bottom = last.get(b);
    if (top === undefined || bottom === undefined || top === bottom) continue;
    paths.push(
      <line
        key={`rail-${b}`}
        x1={laneX(l)}
        y1={cy(top)}
        x2={laneX(l)}
        y2={cy(bottom)}
        stroke={laneColor(l, dark)}
        strokeWidth={2}
        opacity={0.75}
      />,
    );
  }
  for (const f of forks(rows, nodes)) {
    const l = lanes.lane.get(f.branch);
    if (l === undefined) continue;
    const pl = (f.toBranch !== null ? lanes.lane.get(f.toBranch) : undefined) ?? l;
    const x0 = laneX(l);
    const y0 = cy(f.from);
    const x1 = laneX(pl);
    const y1 = cy(f.to);
    paths.push(
      <path
        key={`fork-${f.branch}`}
        d={`M ${x0} ${y0} C ${x0} ${(y0 + y1) / 2}, ${x1} ${(y0 + y1) / 2}, ${x1} ${y1}`}
        fill="none"
        stroke={laneColor(l, dark)}
        strokeWidth={2}
        opacity={0.75}
      />,
    );
  }
  return (
    <svg width={width} height={height} className="absolute top-0 left-0" aria-hidden="true">
      {paths}
      {rows.map((r, i) => {
        const b = branchOfRow(r);
        if (b === null) return null;
        const l = lanes.lane.get(b) ?? 0;
        const color = laneColor(l, dark);
        const x = laneX(l);
        const y = cy(i);
        if (r.kind === "branch") {
          return (
            <circle
              key={`h-${b}`}
              cx={x}
              cy={y}
              r={3}
              fill={r.folded ? color : "var(--color-bg)"}
              stroke={color}
              strokeWidth={1.5}
            />
          );
        }
        if (r.kind !== "node") return null;
        const n = r.node;
        return (
          <g key={n.id}>
            {n.id === activeNode && (
              <circle cx={x} cy={y} r={7} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} />
            )}
            <circle
              cx={x}
              cy={y}
              r={4}
              fill={n.id === viewNode ? color : "var(--color-bg)"}
              stroke={color}
              strokeWidth={2}
            />
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------- pieces

function MetricsText({
  byId,
  id,
  className,
}: {
  byId: ReadonlyMap<string, RefineNode>;
  id: string;
  className?: string;
}) {
  const mv = metricsView(byId, id);
  if (mv.r1 === null) return null;
  return (
    <span
      className={cx(
        "shrink-0 font-mono text-2xs tabular-nums",
        mv.current ? "text-ink-2" : "text-ink-3 opacity-80",
        className,
      )}
      title={mv.current ? undefined : `${t.treeInheritedTip}${mv.source ? t.paren(mv.source) : ""}`}
    >
      R1 {mv.r1.toFixed(4)}
      {!mv.current && (
        <span className="ml-1">
          · {t.treeInherited}
          {mv.source ? ` ${mv.source}` : ""}
        </span>
      )}
    </span>
  );
}

function DeliveredChip({ marks }: { marks: DeliveryMark[] }) {
  const newest = marks[marks.length - 1];
  const tone = deliveryTone(newest.status);
  return (
    <span
      data-testid="tree-delivered"
      title={`${t.treeDeliveredTip}\n${marks
        .map((m) => `${m.rel} · ${deliveryStatusLabel(m.status)}`)
        .join("\n")}`}
      className={cx("shrink-0 rounded-md px-1 text-2xs font-medium", tone)}
    >
      {t.treeDelivered}
      {marks.length > 1 ? ` ×${marks.length}` : ""}
    </span>
  );
}

// ------------------------------------------------------------ branch compare

function BranchCompareCard({
  lanes,
  dark,
  byId,
}: {
  lanes: Lanes;
  dark: boolean;
  byId: ReadonlyMap<string, RefineNode>;
}) {
  const { state, viewNode: viewNodeAction } = useCrystal();
  const [open, toggle] = useSection("nodes.compare", false);

  const rows = useMemo(
    () =>
      Object.entries(state.branches)
        .filter(([branch]) => !isDiagBranch(branch))
        .map(([branch, headId]) => ({
          branch,
          headId,
          head: byId.get(headId) ?? null,
          mv: metricsView(byId, headId),
        })),
    [state.branches, byId],
  );
  if (rows.length < 2) return null;

  const bestR1 = rows.reduce<number | null>((best, r) => {
    if (!r.mv.current || r.mv.r1 === null) return best;
    return best === null || r.mv.r1 < best ? r.mv.r1 : best;
  }, null);
  const viewingBranch = state.nodes.find((n) => n.id === state.viewNode)?.branch ?? null;
  const f = (v: number | null | undefined, d: number): string =>
    v === null || v === undefined ? "—" : v.toFixed(d);

  return (
    <div className="mx-3 mt-2 rounded-card border border-line bg-surface">
      <button
        type="button"
        aria-expanded={open}
        title={open ? t.treeCompareClose : t.treeCompareOpen}
        onClick={toggle}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left select-none"
      >
        <IconChevronRight
          size={11}
          className={cx("shrink-0 text-ink-3 transition-transform", open && "rotate-90")}
        />
        <span className="text-2xs font-medium text-ink-2">{t.branchCompareTitle}</span>
        <span className="text-2xs text-ink-3">
          {rows.length} · {t.treeCompareNote}
        </span>
      </button>
      {open && (
        <div className="overflow-x-auto px-2.5 pb-2">
          <table className="w-full border-collapse font-mono text-2xs tabular-nums">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="py-1 pr-2 font-medium">{t.branchLabel}</th>
                <th className="py-1 pr-2 font-medium">{t.branchHead}</th>
                <th className="py-1 pr-2 text-right font-medium">R1</th>
                <th className="py-1 pr-2 text-right font-medium">wR2</th>
                <th className="py-1 pr-2 text-right font-medium">GooF</th>
                <th className="py-1 pr-2 text-right font-medium">{t.peakLabel}</th>
                <th className="py-1 text-right font-medium">{t.paramsLabel}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isBest = bestR1 !== null && r.mv.current && r.mv.r1 === bestR1;
                const isViewing = r.branch === viewingBranch;
                const lane = lanes.lane.get(r.branch);
                return (
                  <tr
                    key={r.branch}
                    onClick={() => viewNodeAction(r.headId)}
                    title={isViewing ? t.branchViewing : `${t.checkoutBtn} ${r.headId}`}
                    className={cx(
                      "cursor-pointer border-t border-line/60 transition-colors",
                      isViewing ? "bg-accent/8 text-ink" : "text-ink-2 hover:bg-raised/40",
                    )}
                  >
                    <td className="max-w-24 py-1 pr-2">
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{
                            backgroundColor:
                              lane === undefined ? "var(--color-line)" : laneColor(lane, dark),
                          }}
                          aria-hidden="true"
                        />
                        <span className="truncate" title={r.branch}>
                          {r.branch}
                        </span>
                      </span>
                    </td>
                    <td className="py-1 pr-2">{r.headId}</td>
                    <td
                      className={cx(
                        "py-1 pr-2 text-right",
                        isBest && "font-semibold text-ink-2",
                        !r.mv.current && "text-ink-3",
                      )}
                      title={
                        r.mv.current || r.mv.source === null
                          ? undefined
                          : `${t.treeInherited} ${r.mv.source}`
                      }
                    >
                      {f(r.mv.r1, 4)}
                      {isBest && (
                        <span title={t.treeBestTip} className="ml-0.5 text-ink-3">
                          ·
                        </span>
                      )}
                      {!r.mv.current && r.mv.r1 !== null && (
                        <span className="ml-0.5 opacity-70">*</span>
                      )}
                    </td>
                    <td className={cx("py-1 pr-2 text-right", !r.mv.current && "text-ink-3")}>
                      {f(r.mv.wr2, 4)}
                    </td>
                    <td className={cx("py-1 pr-2 text-right", !r.mv.current && "text-ink-3")}>
                      {f(r.mv.goof, 2)}
                    </td>
                    <td className="py-1 pr-2 text-right">{f(r.head?.diff_map_max, 2)}</td>
                    <td className="py-1 text-right">
                      {r.head?.n_params !== null && r.head?.n_params !== undefined && r.head.n_params > 0
                        ? r.head.n_params
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="pt-1 text-2xs text-ink-3">* {t.treeInheritedTip}</div>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- panel

export function NodeTreePanel() {
  const { state, viewNode: viewNodeAction, beginComparison } = useCrystal();
  const draft = useComposerDraft();
  const { theme } = useTheme();
  const dark = theme === "dark";

  const [overrides, setOverrides] = useState<Map<string, boolean>>(() => new Map());
  const [diagOpen, toggleDiag] = useSection("nodes.diagOpen", false);
  const folds = useMemo<FoldState>(
    () => ({ branches: overrides, diag: !diagOpen }),
    [overrides, diagOpen],
  );
  const lay = useMemo(() => layout(state.nodes, folds), [state.nodes, folds]);
  const byId = useMemo(() => new Map(state.nodes.map((n) => [n.id, n])), [state.nodes]);
  const best = useMemo(() => bestNodeId(state.nodes), [state.nodes]);
  const delivered = useMemo(() => deliveriesByNode(state.deliveries), [state.deliveries]);

  const toggleBranch = (b: string) =>
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(b, !isFolded(b, { branches: prev, diag: !diagOpen }));
      return next;
    });
  const keyActivate = (fn: () => void) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="node-tree">
      <BranchCompareCard lanes={lay.lanes} dark={dark} byId={byId} />
      <div className="min-h-0 flex-1 overflow-y-auto px-1 pt-2 pb-3">
        <div className="relative">
          <GraphSvg
            lay={lay}
            nodes={state.nodes}
            activeNode={state.activeNode}
            viewNode={state.viewNode}
            dark={dark}
          />
          {lay.rows.map((r) => {
            if (r.kind === "diag") {
              return (
                <div
                  key="diag"
                  role="button"
                  tabIndex={0}
                  data-testid="tree-diag"
                  aria-expanded={!r.folded}
                  title={t.treeDiagGroupTip}
                  onClick={toggleDiag}
                  onKeyDown={keyActivate(toggleDiag)}
                  style={{ height: HEAD_H, paddingLeft: lay.width }}
                  className="flex cursor-pointer items-center gap-1.5 rounded-md pr-2 text-2xs text-ink-3 transition-colors hover:bg-raised/40"
                >
                  <IconChevronRight
                    size={11}
                    className={cx("shrink-0 transition-transform", !r.folded && "rotate-90")}
                  />
                  <span className="font-medium">{t.treeDiagGroup}</span>
                  <span className="tabular-nums">
                    {r.branches} {t.treeBranchesUnit} · {r.nodes} {t.treeNodesUnit}
                  </span>
                </div>
              );
            }
            if (r.kind === "branch") {
              const isActiveBranch = r.branch === state.activeBranch;
              return (
                <div
                  key={`b-${r.branch}`}
                  role="button"
                  tabIndex={0}
                  data-testid="tree-branch"
                  data-folded={r.folded ? "1" : "0"}
                  aria-expanded={!r.folded}
                  title={`${r.branch}\n${t.treeFoldTip}`}
                  onClick={() => toggleBranch(r.branch)}
                  onKeyDown={keyActivate(() => toggleBranch(r.branch))}
                  style={{ height: HEAD_H, paddingLeft: lay.width }}
                  className="flex cursor-pointer items-center gap-1.5 rounded-md pr-2 text-2xs transition-colors hover:bg-raised/40"
                >
                  <IconChevronRight
                    size={11}
                    className={cx("shrink-0 text-ink-3 transition-transform", !r.folded && "rotate-90")}
                  />
                  <span className="min-w-0 truncate font-mono font-medium text-ink-2">{r.branch}</span>
                  {isActiveBranch && <span className="shrink-0 text-accent">{t.activeTag}</span>}
                  <span className="shrink-0 text-ink-3 tabular-nums">
                    {r.count} {t.treeNodesUnit}
                  </span>
                  {r.folded && (
                    <span className="ml-auto flex min-w-0 shrink items-baseline gap-1.5 font-mono text-ink-3 tabular-nums">
                      <span>{r.head.id}</span>
                      <MetricsText byId={byId} id={r.head.id} />
                    </span>
                  )}
                </div>
              );
            }
            const n = r.node;
            const isViewed = n.id === state.viewNode;
            const asuBad = n.asu != null && (n.asu.detached > 0 || n.asu.ghosts > 0);
            const asuTip = asuBad
              ? t.asuFlagTipPrefix +
                [
                  n.asu!.detached > 0 ? `${t.asuFlagDetached}×${n.asu!.detached}` : "",
                  n.asu!.ghosts > 0 ? `${t.asuFlagGhosts}×${n.asu!.ghosts}` : "",
                ]
                  .filter(Boolean)
                  .join(t.sepList) +
                t.asuFlagTipSuffix
              : undefined;
            const marks = delivered.get(n.id) ?? [];
            return (
              <div
                key={n.id}
                data-testid="tree-node"
                data-node={n.id}
                aria-current={isViewed ? "true" : undefined}
                style={{ height: NODE_H, paddingLeft: lay.width }}
                className={cx(
                  "group flex cursor-pointer items-center rounded-lg pr-2 transition-colors",
                  isViewed ? "bg-raised/80" : "hover:bg-raised/40",
                )}
              >
                <button type="button" aria-label={t.crystal.viewNodeAria(n.id)} onClick={() => viewNodeAction(n.id)}
                  className="min-w-0 flex-1 rounded-md pl-1 text-left">
                  <div className="flex items-baseline gap-1.5">
                    <span className="shrink-0 font-mono text-2xs font-semibold text-ink">{n.id}</span>
                    {n.id === state.activeNode && (
                      <span className="shrink-0 text-2xs text-accent">{t.activeTag}</span>
                    )}
                    {asuBad && (
                      <span title={asuTip} className="shrink-0 text-2xs text-danger">
                        ⚑
                      </span>
                    )}
                    {marks.length > 0 && <DeliveredChip marks={marks} />}
                    {n.id === best && (
                      <span
                        data-testid="tree-best"
                        title={t.treeBestTip}
                        className="shrink-0 rounded-md bg-raised px-1 text-2xs font-medium text-ink-3"
                      >
                        {t.branchBest}
                      </span>
                    )}
                    <span className="min-w-0 truncate text-2xs text-ink-2">{n.tool}</span>
                    <MetricsText byId={byId} id={n.id} className="ml-auto pl-1.5" />
                  </div>
                  {n.note !== "" && (
                    <div className="truncate text-2xs leading-tight text-ink-3">{n.note}</div>
                  )}
                </button>
                <button
                  type="button"
                  data-comparison-node={n.id}
                  title={t.compareBaselineTip}
                  disabled={n.id === (state.comparison?.node ?? state.viewNode)}
                  onClick={() => beginComparison(n.id)}
                  className={cx(
                    "ml-1.5 h-7 shrink-0 rounded-md border px-1.5 text-xs transition-opacity focus-visible:opacity-100 group-focus-within:opacity-100 disabled:cursor-not-allowed disabled:opacity-40",
                    state.comparison?.baseline === n.id
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : "border-line text-ink-3 md:opacity-0 group-hover:opacity-100 hover:bg-raised hover:text-ink",
                  )}
                >
                  {t.compareBtn}
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    draft.insert(`${t.checkoutTemplatePrefix}${n.id}${t.checkoutTemplateSuffix}`);
                  }}
                  className="ml-1.5 h-5 shrink-0 rounded-md border border-line px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-raised hover:text-ink"
                >
                  {t.checkoutBtn}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
