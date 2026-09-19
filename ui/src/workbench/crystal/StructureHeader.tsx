/** Structure header card, above every crystal tab.
 *
 * Modelled on Olex2's info panel (design_ref/front-end/olex2-2.png): who
 * this structure is, its cell, and the numbers you judge it by, all
 * readable at once instead of a row of same-looking chips. The previous
 * strip showed R1/wR2/GooF/peak/params and nothing else - the cell, the
 * space group and every data-side number lived one tab away, so the
 * question "is this R1 good FOR THIS CRYSTAL" could not be answered
 * without leaving the view.
 *
 * One thing deliberately NOT taken from Olex2: it colour-codes each tile
 * green/yellow/red against fixed cutoffs. What counts as a good Rint or
 * d_min depends on the crystal and the question - a 0.57 Rint is
 * disqualifying for a small organic and unremarkable for a weakly
 * diffracting framework - so a traffic light here would put a verdict on
 * a number that needs context. The tiles carry the number and the label;
 * the judgement stays with the reader.
 */
import { Fragment, useMemo } from "react";
import { cx } from "../../lib/format";
import { metricDelta as deltaOf } from "../../lib/metricDelta";
import { comparableMetric, signedDifference } from "../../lib/structureComparison";
import { structureQuote } from "../../lib/quote";
import { formulaCount, hillFormula } from "../../lib/formula";
import { zh } from "../../lib/zh";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useCrystal } from "../../state/CrystalProvider";
import { useThreadOptional } from "../../state/ThreadProvider";
import type { RefineNode, SceneCell } from "../../lib/wbTypes";
import { extentLabel } from "./extent";
import { useSection } from "./useSection";

function Tile({
  label,
  note,
  value,
  sub,
  title,
  dim,
}: {
  label: string;
  note?: string;
  value: string;
  sub?: string;
  title?: string;
  dim?: boolean;
}) {
  // Olex2's proportion: a small label pinned top-left over an optional
  // second line of qualifier ("d min (CuKα)" / "2Θ=138.6°"), the number
  // large and pushed to the bottom-right. The label is chrome you read
  // once; the number is what you come back to.
  return (
    <div
      title={title}
      className={cx(
        "flex min-h-[2.3rem] min-w-0 flex-col rounded-md bg-raised/70 px-1.5 pt-1 pb-1",
        dim && "opacity-55",
      )}
    >
      <span className="truncate text-2xs leading-none text-ink-3">
        {label}
      </span>
      {note && (
        <span className="truncate font-mono text-2xs leading-tight text-ink-3">
          {note}
        </span>
      )}
      <span className="mt-auto truncate pt-0.5 text-right font-mono text-sm leading-none font-medium text-ink tabular-nums">
        {value}
        {sub && (
          <span className="ml-0.5 text-2xs font-normal text-ink-3">
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}

/** One statistic on the collapsed key bar: italic serif stem, the number,
 * and the coloured delta against the parent when there is one. */
function KeyStat({
  stem,
  sub,
  cur,
  prev,
  digits,
  ideal,
  strong,
  dim,
  comparable = false,
}: {
  stem: string;
  sub?: string;
  cur: number | null;
  prev: number | null | undefined;
  digits: number;
  ideal?: number;
  strong?: boolean;
  dim?: boolean;
  comparable?: boolean;
}) {
  const { changed, improved, worsened, direction } = deltaOf(cur, prev, digits, ideal, dim, comparable);
  return (
    <span className={cx("inline-flex items-baseline gap-1 whitespace-nowrap", dim && "opacity-55")}>
      <span className="font-serif text-2xs italic text-ink-3">
        {stem}
        {sub && <sub className="text-[0.8em] not-italic">{sub}</sub>}
      </span>
      <span className={cx("font-mono tabular-nums", strong ? "text-sm font-semibold text-ink" : "text-xs text-ink")}>
        {cur === null ? "—" : cur.toFixed(digits)}
      </span>
      {changed && (
        <span
          className={cx("font-mono text-2xs tabular-nums", improved ? "text-ok" : worsened ? "text-danger" : "text-ink-3")}
          title={`${zh.headerVsParent} ${(prev as number).toFixed(digits)} · ${comparable ? "条件可比" : "条件未明或不同，仅显示数值变化"}`}
        >
          {direction === "up" ? "▲" : direction === "down" ? "▼" : ""}
          {direction ? Math.abs((cur as number) - (prev as number)).toFixed(digits) : signedDifference(cur, prev, digits)}
        </span>
      )}
    </span>
  );
}

/** R factor with its change since the parent node. The arrow is the only
 * colour in the card, and it is a comparison against this structure's own
 * history rather than a verdict against a cutoff. */
function RFactor({
  stem,
  sub,
  cur,
  prev,
  digits,
  ideal,
  big,
  dim,
  comparable = false,
}: {
  stem: string;
  sub?: string;
  cur: number | null;
  prev: number | null | undefined;
  digits: number;
  /** Value the statistic is defined to sit at, when it has one. R factors
   * do not (smaller is a smaller residual, full stop); GooF does - it is 1
   * when the weights match the residuals, and 0.94 → 0.96 is a move TOWARD
   * that, not away from it. Without this the arrow called every GooF rise
   * a regression, including the ones that fixed the weighting. */
  ideal?: number;
  big?: boolean;
  dim?: boolean;
  comparable?: boolean;
}) {
  const { changed, improved, worsened, direction } = deltaOf(cur, prev, digits, ideal, dim, comparable);
  // R1 is the largest thing in the panel on purpose - it is what the eye
  // should land on, the way Olex2 sets it, and the label is set the way
  // the literature sets it (italic serif stem, subscripted order) rather
  // than as the ASCII "R1" that only exists because .lst files are plain
  // text. The delta is the only colour here, and it compares against this
  // structure's own last step rather than against a cutoff.
  return (
    <div
      className={cx(
        "flex items-baseline justify-end gap-1.5",
        dim && "opacity-55",
      )}
    >
      <span className="mr-auto font-serif text-xs italic text-ink-3">
        {stem}
        {sub && <sub className="text-2xs not-italic">{sub}</sub>}
      </span>
      {changed && (
        <span
          className={cx(
            "font-mono text-2xs tabular-nums",
            improved ? "text-ok" : worsened ? "text-danger" : "text-ink-3",
          )}
          title={`${zh.headerVsParent} ${(prev as number).toFixed(digits)} · ${comparable ? "条件可比" : "条件未明或不同，仅显示数值变化"}`}
        >
          {/* the arrow is the direction the NUMBER moved; the colour is
           * whether that was the right way. For an R factor the two always
           * agree, for GooF they need not. */}
          {direction === "up" ? "▲" : direction === "down" ? "▼" : ""}
          {direction ? Math.abs((cur as number) - (prev as number)).toFixed(digits) : signedDifference(cur, prev, digits)}
        </span>
      )}
      <span
        className={cx(
          "font-mono tabular-nums",
          big
            ? "text-2xl leading-none font-semibold tracking-tight text-ink"
            : "text-xs leading-none text-ink-2",
        )}
      >
        {cur === null ? "—" : cur.toFixed(digits)}
      </span>
    </div>
  );
}

/** The cell, laid out the way Olex2 lays it out: lengths in one column,
 * angles in the next, the derived quantity in the third. Reading down a
 * column is how you spot a metric relation - a = b, or all three angles
 * 90° - and that recognition is the first step of every space-group
 * argument. A single flowing line hides it. */
function CellBlock({ cell }: { cell: SceneCell }) {
  const rows: [string, number, string, number][] = [
    ["a", cell.a, "α", cell.alpha],
    ["b", cell.b, "β", cell.beta],
    ["c", cell.c, "γ", cell.gamma],
  ];
  return (
    <div className="grid shrink-0 grid-cols-[auto_auto] gap-x-3 gap-y-[3px] font-mono text-2xs leading-none tabular-nums">
      {rows.map(([e, len, ang, deg]) => (
        <Fragment key={e}>
          <span className="text-ink">
            <span className="mr-0.5 font-serif text-2xs italic text-accent/85">
              {e}
            </span>
            <span className="text-ink-3"> = </span>
            {len.toFixed(3)}
          </span>
          <span className="text-ink">
            <span className="mr-0.5 font-serif text-2xs text-accent/85">
              {ang}
            </span>
            <span className="text-ink-3"> = </span>
            {deg.toFixed(2)}
            <span className="text-ink-3">°</span>
          </span>
        </Fragment>
      ))}
      <span className="text-ink">
        <span className="mr-0.5 font-serif text-2xs italic text-accent/85">
          V
        </span>
        <span className="text-ink-3"> = </span>
        {Math.round(cell.volume)}
        <span className="ml-0.5 text-2xs text-ink-3">Å³</span>
      </span>
    </div>
  );
}

export function StructureHeader() {
  const { state, comparisonInfo } = useCrystal();
  const draft = useComposerDraft();
  const thread = useThreadOptional();
  // collapsed by default since R1.2: the pane is the crystal's; a two-line
  // key bar carries what you glance at, the card opens for the rest
  const [open, toggle] = useSection("header2", false);
  const viewed = state.nodes.find((n) => n.id === state.viewNode);
  const scene = state.sceneNode === state.viewNode ? state.scene : null;
  const formula = useMemo(() => {
    const asu = scene?.atoms.filter((atom) => !atom.sym && atom.flag !== "removed");
    // A packed range can omit identity-position sites. Never label that
    // partial subset as the complete ASU composition.
    return asu && asu.length === viewed?.n_atoms ? hillFormula(asu) : null;
  }, [scene, viewed?.n_atoms]);
  if (!viewed) return null;
  const parent = state.nodes.find((n) => n.id === viewed.parent) ?? null;
  const canCompare = (metric: "r1" | "wr2" | "goof") => comparableMetric(comparisonInfo?.data ?? null, metric, viewed, parent ?? undefined);
  const isActive = viewed.id === state.activeNode;
  const stale = !viewed.structure_only && !viewed.metrics_current;
  // a geometry-only commit has no measurement of its own: show the nearest
  // measured ancestor's R factors dimmed and named, not "—" (which the
  // user read as "the refinement was lost", usertest test3-2 2026-09-08)
  const inh = viewed.r1 === null && !viewed.structure_only ? (viewed.metrics_inherited ?? null) : null;
  const inherited = inh !== null;
  const r1 = viewed.r1 ?? inh?.r1 ?? null;
  const wr2 = viewed.wr2 ?? inh?.wr2 ?? null;
  const goof = viewed.goof ?? inh?.goof ?? null;
  const dimR = stale || inherited;

  // Peak / params belong to the VIEWED node. Only while a turn is live in
  // follow mode may the thread's metrics cursor bridge the gap until the
  // nodes refetch lands.
  const liveFollow = state.follow && thread?.state.turn.active === true;
  const cursor = liveFollow && isActive ? thread?.state.metricsCursor : undefined;
  const peak = cursor?.diffMapMax ?? viewed.diff_map_max;
  const nParams = cursor?.nParams ?? viewed.n_params;

  // Rint / d_min / completeness bound what R1 was ever going to reach, so
  // they belong beside R1. Nodes committed before the data block existed
  // have none of their own; the provider recovers those from the project's
  // current reflection file, which is a WEAKER claim (the data can have
  // been swapped since) and is marked as such rather than passed off as
  // the node's own record.
  const recovered =
    viewed.data == null && state.dataBlockNode === viewed.id
      ? state.dataBlock
      : null;
  const d = viewed.data ?? recovered?.data ?? undefined;
  const dRecomputed = recovered?.source === "computed";
  const cell = scene?.cell;
  const sg = scene?.space_group ?? d?.space_group;

  // refinement_tools writes n_params = -1 when the reparametrisation count
  // cannot be read; it means "unknown", and rendering it as -1 (which the
  // old strip did) states a falsehood about the refinement
  const params = nParams !== null && nParams !== undefined && nParams > 0
    ? nParams
    : null;

  type TileProps = Parameters<typeof Tile>[0];
  const tiles: TileProps[] = [];
  const push = (t: TileProps | null) => {
    if (t) tiles.push(t);
  };
  // a recomputed block is drawn dim throughout, so "these came from the
  // current hkl, not from this node" is visible on the tiles themselves
  // rather than only in a tooltip somewhere
  const dTip = dRecomputed ? `\n${zh.headerDataRecomputed}` : "";
  push(d?.d_min === undefined ? null : {
    label: zh.headerDmin, value: d.d_min.toFixed(2), sub: "Å",
    // SHEL and d_min disagreeing is not a bug: the in-process engine
    // ignores SHEL by design, so the merged d_min can be finer than the
    // cutoff the refinement was told to use. Say so where they collide.
    note: d.shel ?? undefined,
    title: zh.headerDminTip + dTip, dim: dRecomputed,
  });
  push(d?.r_int === undefined ? null : {
    label: "Rint",
    // Olex2 puts the multiplicity under Rint and it belongs there: the
    // same 0.08 means one thing at m=2 and another at m=8, so a bare
    // Rint is a number you cannot finish reading
    note: d.n_obs && d.n_unique
      ? `m = ${(d.n_obs / d.n_unique).toFixed(1)}`
      : undefined,
    value: d.r_int.toFixed(3),
    title: zh.headerRintTip + dTip, dim: dRecomputed,
  });
  push(d?.completeness === undefined ? null : {
    label: zh.headerCompleteness,
    value: (d.completeness * 100).toFixed(1), sub: "%",
    title: dRecomputed ? zh.headerDataRecomputed : undefined,
    dim: dRecomputed,
  });
  push(d?.n_unique === undefined ? null : {
    label: zh.headerUnique, value: String(d.n_unique),
    title: zh.headerUniqueTip + dTip, dim: dRecomputed,
  });
  push(peak === null || peak === undefined ? null : {
    label: zh.headerPeak, value: peak.toFixed(2), sub: "e", dim: stale,
  });
  push(viewed.diff_map_min === null ? null : {
    label: zh.headerHole, value: viewed.diff_map_min.toFixed(2), sub: "e",
    dim: stale,
  });
  push(params === null ? null : {
    label: zh.paramsLabel, value: String(params),
    // data-to-parameter ratio: the cheapest check that the model has not
    // been given more freedom than the data can pay for
    note: d?.n_unique
      ? `数据/参数 ${(d.n_unique / params).toFixed(1)}`
      : undefined,
    sub: viewed.n_restraints > 0 ? `+${viewed.n_restraints}` : undefined,
    title: zh.headerParamsTip, dim: stale,
  });
  // Flack gets a tile when it exists and no tile when it does not. The atom
  // count used to sit here, and it earned its place back when the card had
  // no formula line - now the formula states it twice over (and the status
  // line a third time), so a tile for it was pure duplication.
  push(viewed.flack === undefined ? null : {
    label: "Flack", value: viewed.flack.toFixed(2), title: zh.headerFlackTip,
  });

  // Asymmetric-unit content in Hill order, the line Olex2 gives the most
  // prominence after the structure name. Taken from the identity-operator
  // atoms, so it stays the ASU's formula in every mode rather than
  // ballooning when you pack or grow.
  // Occupancy-weighted (lib/formula.ts): counting sites showed the
  // reg10-dbu two-position disorder twice (C18H24 for a C16H20 salt).
  // plain text of the same formula, for the tooltip of a truncated one
  const formulaText = (formula ?? [])
    .map(({ elem, count }) => `${elem}${count !== 1 ? formulaCount(count) : ""}`)
    .join("");

  // The model's atom count (a tile above) and the SCENE's atom count are
  // different things once you grow or pack, and confusing them is easy -
  // hence a separate line that says what is drawn, not what is modelled,
  // and names the extent that made it so. This is Olex2's "Structure ...
  // loaded | Polymeric structure" slot: one line of what you are actually
  // looking at, under everything that describes the model itself.
  const m = scene?.meta;
  const sceneCounts = m
    ? [
        `绘制 ${m.n_atoms} ${zh.atomsLabel}`,
        `${m.n_bonds} 键`,
        m.n_polyhedra > 0 ? `${m.n_polyhedra} 多面体` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  return (
    <div className="min-w-0 shrink-0 border-b border-line @container">
      {/* identity bar, two fixed rows (round-3 R2-B). Row 1 is WHO: the
       * node chip, the branch (gives way first; full name in the tooltip),
       * the space group top-right in Olex2's italics - the single most
       * consequential claim on the screen and the one most often wrong -
       * and 引用. Row 2, while the card is folded, is HOW WELL and WHAT:
       * the formula, R1/wR2/GooF and the scene counts. Every truncation
       * keeps its text in a title: the 2026-09-05 review found
       * "hypothesis/pBrAc…" and "C12.67H6Br0.15O6.…" cut with nowhere to
       * read them. */}
      <div className="@container">
        <div className="flex min-w-0 items-center gap-1 px-3 pt-1.5 pb-1" data-testid="identity-row1">
          <button type="button" aria-expanded={open} aria-controls="structure-details"
            title={open ? zh.headerCollapse : zh.headerExpand} onClick={toggle}
            className="flex min-w-0 flex-1 items-baseline gap-2 rounded py-1 text-left hover:bg-raised/40 focus-visible:outline-2 focus-visible:outline-accent">
            <span className={cx("shrink-0 rounded-md px-1.5 py-0.5 font-mono text-xs font-medium",
              isActive ? "bg-accent/12 text-accent" : "bg-raised text-ink")}>{viewed.id}</span>
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-3" title={viewed.branch}>{viewed.branch}</span>
            {sg && <span className="max-w-[40%] truncate font-serif text-md italic text-ink" title={`${zh.headerSpaceGroupTip} · ${sg}`}>{sg}</span>}
            <span aria-hidden="true" className={cx("shrink-0 text-2xs text-ink-3", open && "rotate-90")}>▶</span>
          </button>
          <button type="button" title={zh.headerQuoteTip}
            onClick={() => draft.insert(structureQuote({
              node: viewed.id, spaceGroup: sg, cell, r1: viewed.r1, wr2: viewed.wr2,
              goof: viewed.goof, nAtoms: viewed.n_atoms, nParams: params,
              nRestraints: viewed.n_restraints, peak, hole: viewed.diff_map_min, data: d,
            }))}
            className="shrink-0 rounded-pill px-2 py-1 text-xs text-ink-3 hover:bg-accent/10 hover:text-accent focus-visible:outline-2 focus-visible:outline-accent">
            {zh.headerQuote}
          </button>
        </div>

        {/* key row (collapsed): the formula, the three statistics and what
         * is drawn - one glance, no card. Everything else waits behind the
         * chevron. The counts step aside below 480 px (the default pane on
         * a 1440 px window is 432) so the formula and the numbers never
         * truncate for their sake; the extent pill on the canvas and the
         * open card still name the slice and its counts. */}
        {!open && (
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 px-3 pb-1.5" data-testid="identity-row2">
            {formula && (
              <span
                className="min-w-0 shrink truncate font-serif text-sm text-ink"
                title={`${formulaText}\n${zh.headerFormulaTip}`}
              >
                {formula.map(({ elem, count }) => (
                  <span key={elem}>
                    {elem}
                    {count !== 1 && <sub className="text-[0.75em]">{formulaCount(count)}</sub>}
                  </span>
                ))}
              </span>
            )}
            {!formula && <span className="text-xs text-ink-3" title="完整 ASU 组成未包含在当前显示范围中">{viewed.n_atoms} ASU 原子</span>}
            <KeyStat stem="R" sub="1" cur={r1} prev={inherited ? undefined : parent?.r1} digits={4} strong dim={dimR} comparable={canCompare("r1")} />
            <KeyStat stem="wR" sub="2" cur={wr2} prev={inherited ? undefined : parent?.wr2} digits={4} dim={dimR} comparable={canCompare("wr2")} />
            <KeyStat stem="GooF" cur={goof} prev={inherited ? undefined : parent?.goof} digits={2} ideal={1} dim={dimR} comparable={canCompare("goof")} />
            {inherited && (
              <span className="font-mono text-2xs text-ink-3" title={zh.headerInheritedTip}>
                {zh.headerInherited} {inh.from}
              </span>
            )}
            {sceneCounts && (
              <span
                className="ml-auto hidden min-w-0 truncate font-mono text-2xs text-ink-3 tabular-nums @min-[30rem]:inline"
                title={sceneCounts}
              >
                {sceneCounts}
              </span>
            )}
          </div>
        )}
      </div>

      {!open && (stale || viewed.asu?.detached || viewed.asu?.ghosts) ? (
        <div className="px-3 pb-1.5 text-xs text-warn">
          {[stale ? zh.staleMetrics : null,
            viewed.asu?.detached ? `${zh.asuFlagDetached} ${viewed.asu.detached}` : null,
            viewed.asu?.ghosts ? `${zh.asuFlagGhosts} ${viewed.asu.ghosts}` : null].filter(Boolean).join(" · ")}
        </div>
      ) : null}
      {open && (
        <div id="structure-details" className="max-h-[35vh] overflow-y-auto flex flex-col gap-1.5 px-3 pb-1.5">
          {/* the formula gets the size Olex2 gives it. It is the one line
           * that says WHAT this is rather than how well it is refined, and
           * on a framework it is the fastest check that the ASU is the
           * chemistry you think it is. */}
          {formula && (
            <div
              className="truncate pt-0.5 font-serif text-2xl leading-none text-ink"
              title={zh.headerFormulaTip}
            >
              {formula.map(({ elem, count }) => (
                <span key={elem}>
                  {elem}
                  {count !== 1 && (
                    <sub className="text-2xs text-ink-2">{formulaCount(count)}</sub>
                  )}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-start gap-3">
            {cell && <CellBlock cell={cell} />}
            <div className="ml-auto flex w-[7.5rem] shrink-0 flex-col gap-1.5">
              <RFactor
                stem="R"
                sub="1"
                cur={r1}
                comparable={canCompare("r1")}
                prev={inherited ? undefined : parent?.r1}
                digits={4}
                big
                dim={dimR}
              />
              <RFactor
                stem="wR"
                sub="2"
                cur={wr2}
                comparable={canCompare("wr2")}
                prev={inherited ? undefined : parent?.wr2}
                digits={4}
                dim={dimR}
              />
              <RFactor
                stem="GooF"
                cur={goof}
                comparable={canCompare("goof")}
                prev={inherited ? undefined : parent?.goof}
                digits={2}
                ideal={1}
                dim={dimR}
              />
            </div>
          </div>

          {/* only tiles that have a number. A grid of eight em-dashes reads
           * as "the app is broken" rather than "this node predates the
           * data block", and an absent number is not information. */}
          {tiles.length > 0 && (
            <div className="grid grid-cols-2 gap-1 @min-[24rem]:grid-cols-4">
              {tiles.map((t) => (
                <Tile key={t.label} {...t} />
              ))}
            </div>
          )}

          {/* what is on screen right now: the extent in the toolbar's own
           * words, then the scene's own counts. Both move with 生长 while
           * everything above them stays put, which is the whole reason
           * they are separated by a rule instead of mixed in. */}
          {sceneCounts && (
            <div className="flex items-baseline gap-1.5 border-t border-line/60 pt-1.5 text-2xs">
              <span className="shrink-0 font-medium text-ink-2">
                {extentLabel(state)}
              </span>
              <span className="truncate font-mono text-ink-3">
                {sceneCounts}
              </span>
            </div>
          )}

          {(stale || inherited || dRecomputed || d?.hklf === 5 || viewed.asu) && (
            <div className="flex flex-wrap items-center gap-1 text-2xs">
              {stale && (
                <span
                  className="rounded-md bg-warn/10 px-1.5 py-0.5 text-warn"
                  title={zh.staleMetricsTip}
                >
                  {zh.staleMetrics}
                </span>
              )}
              {inherited && (
                <span
                  className="rounded-md bg-raised px-1.5 py-0.5 text-ink-3"
                  title={zh.headerInheritedTip}
                >
                  {zh.headerInherited} {inh.from}
                </span>
              )}
              {dRecomputed && (
                <span
                  className="rounded-md bg-raised px-1.5 py-0.5 text-ink-3"
                  title={zh.headerDataRecomputed}
                >
                  {zh.headerDataRecomputedChip}
                </span>
              )}
              {d?.hklf === 5 && (
                <span
                  className="rounded-md bg-raised px-1.5 py-0.5 font-mono text-ink-2"
                  title={zh.dataHklf5Tip}
                >
                  HKLF5
                </span>
              )}
              {/* SHEL used to be a chip here; it now rides under the
               * resolution tile, where a cutoff of 0.997 sitting beside a
               * merged d_min of 0.691 is legible as the deliberate
               * difference it is rather than as a contradiction */}
              {viewed.asu && viewed.asu.detached > 0 && (
                <span className="rounded-md bg-warn/10 px-1.5 py-0.5 text-warn">
                  {zh.asuFlagDetached} {viewed.asu.detached}
                </span>
              )}
              {viewed.asu && viewed.asu.ghosts > 0 && (
                <span className="rounded-md bg-warn/10 px-1.5 py-0.5 text-warn">
                  {zh.asuFlagGhosts} {viewed.asu.ghosts}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export type { RefineNode };
