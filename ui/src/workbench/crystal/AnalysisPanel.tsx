/** 分析 tab (round-2 R3.5): the per-node analysis product from
 * GET /api/wb/refine/analysis - the symmetry-unique interaction tables
 * (hydrogen bonds, π–π, C–H···π, C–H···X, halogen, anion–π) with the rule
 * set and the hydrogen provenance they were measured under, the node's
 * pore geometry (volume · dimensionality · LCD), and the blocks that are
 * not computed yet, each with its own note instead of a silent gap.
 *
 * The numbers here are a property of the crystal, not of the picture: the
 * canonical table does not change when the viewer grows the structure,
 * which is what makes a quoted number stable. The viewer's dashed lines
 * are the same engine's display rows. Every row can be quoted into the
 * composer with its labels, operator and geometry - never a viewer
 * ordinal. */
import { useEffect, useMemo, useRef, useState } from "react";
import { interactionIdentity } from "../../lib/analysisInspector";
import { AnalysisInspector } from "./AnalysisInspector";
import { CoordinationSection } from "./CoordinationSection";
import { Spinner } from "../../components/ui";
import { cx } from "../../lib/format";
import {
  criteriaSummary,
  interactionGeometry,
  interactionLabel,
  interactionQuote,
  isIdentityOp,
} from "../../lib/interactions";
import { fragmentQuote, guestQuote, poreQuote, relationName, topologyQuote, withAnchor } from "../../lib/quote";
import { analysisRunning, useAnalysis } from "./useAnalysis";
import {
  INTERACTION_KINDS,
  type AnalysisResponse,
  type AnalysisTopology,
  type AnalysisJob,
  type AnalysisStage,
  type AnalysisStageName,
  type FiniteFragment,
  type GuestEntry,
  type InteractionKind,
  type RingThroughSymmetry,
  type UniqueInteractionRow,
  type VoidEntry,
} from "../../lib/wbTypes";
import { zh } from "../../lib/zh";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useCrystal } from "../../state/CrystalProvider";
import { useWorkbench } from "../../state/WorkbenchProvider";
import {
  isStructureClass,
  sectionsFor,
  STRUCTURE_CLASSES,
  structureClassLabel,
  suggestStructureClass,
  type SectionId,
  type StructureClass,
} from "../../lib/structureClass";
import { IconChevronRight } from "../icons";
import { useSection } from "./useSection";

const ROWS_COLLAPSED = 12;

function SectionHeader({
  title,
  meta,
  open,
  onToggle,
}: {
  title: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="flex w-full items-center gap-1.5 border-b border-line px-3 py-2 text-left text-xs font-medium text-ink transition-colors hover:bg-raised/60"
    >
      <span
        className={cx(
          "inline-flex shrink-0 text-ink-3 transition-transform",
          open && "rotate-90",
        )}
      >
        <IconChevronRight size={12} />
      </span>
      <span>{title}</span>
      {meta !== undefined && (
        <span className="ml-auto font-mono text-2xs text-ink-3 tabular-nums">
          {meta}
        </span>
      )}
    </button>
  );
}

function QuoteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 rounded-md px-2 py-1 text-xs text-ink-3 hover:bg-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
    >
      {zh.anQuote}
    </button>
  );
}

// ---------------------------------------------------------- interactions

function KindBlock({
  kind,
  rows,
  inter,
  node,
}: {
  kind: InteractionKind;
  rows: UniqueInteractionRow[];
  inter: NonNullable<AnalysisResponse["interactions"]>;
  node: string;
}) {
  const draft = useComposerDraft();
  const { state, inspectInteraction } = useCrystal();
  const activeRow = state.inspection?.node === node ? state.inspection.row
    : state.sceneNode === node && state.selection
      ? state.scene?.interactions?.rows.find((r) => r.kind === kind && (r.ai === state.selection?.index || r.bi === state.selection?.index))
      : undefined;
  const activeKey = activeRow ? interactionIdentity(activeRow) : null;
  const activeRef = useRef<HTMLLIElement>(null);
  const [all, setAll] = useState(false);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, [activeKey]);
  const passing = inter.counts.passing[kind] ?? 0;
  const nIntra = inter.counts.intra?.[kind] ?? 0;
  const trunc = inter.truncated[kind];
  const shown = all || rows.findIndex((r) => interactionIdentity(r) === activeKey) >= ROWS_COLLAPSED
    ? rows : rows.slice(0, ROWS_COLLAPSED);
  const crit = criteriaSummary(inter.criteria[kind]);
  const missingRings = ringsThroughSymmetry(inter.criteria[kind]);
  return (
    <div className="border-b border-line/60">
      <div className="flex flex-wrap items-baseline gap-x-2 px-3 pt-2 text-xs">
        <span className="font-medium text-ink">{zh.ixKind[kind] ?? kind}</span>
        <span className="font-mono text-2xs text-ink-3 tabular-nums">
          {zh.anPassing} {passing} / {zh.anOf} {rows.length}
          {nIntra > 0 ? ` · ${zh.anIntra} ${nIntra}` : ""}
        </span>
      </div>
      {crit && (
        <details className="px-3 py-1 text-xs text-ink-3">
          <summary className="cursor-pointer">{zh.ixCriteria}</summary>
          <div className="mt-1 break-words leading-relaxed">{crit}</div>
        </details>
      )}
      {trunc && (
        <div className="px-3 pb-1 text-2xs text-warn">
          {zh.anTruncated} {trunc.cap} / {trunc.found}
        </div>
      )}
      {missingRings.length > 0 && (
        <div className="px-3 pb-1 text-2xs text-warn" title={zh.anMissingRingsTail}>
          {zh.anMissingRings} {missingRings.length}：
          {missingRings.map((r) => `${r.key} × ${r.op}（${r.size} 元）`).join("；")}
          {" · "}
          {zh.anMissingRingsTail}
        </div>
      )}
      <ul className="pb-1">
        {shown.map((r) => (
          <li
            key={interactionIdentity(r)}
            ref={interactionIdentity(r) === activeKey ? activeRef : undefined}
            data-testid="interaction-row"
            data-selected={interactionIdentity(r) === activeKey ? "true" : undefined}
            className={cx("group flex items-start gap-2 px-3 py-1 text-xs hover:bg-raised/50",
              interactionIdentity(r) === activeKey && "bg-accent/10")}
          >
            <span
              className={cx(
                "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                r.passes ? "bg-ok" : "bg-ink-3/50",
              )}
              title={r.passes ? zh.ixPasses : zh.ixFails}
            />
            <button type="button" aria-label={`定位 ${interactionLabel(r)}`} aria-pressed={interactionIdentity(r) === activeKey}
              onClick={() => inspectInteraction(node, r)}
              className="min-w-0 flex-1 rounded py-1 text-left focus-visible:outline-2 focus-visible:outline-accent">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <span className="break-words font-medium text-ink">{interactionLabel(r)}</span>
                {!isIdentityOp(r.op) && (
                  <span className="font-mono text-2xs text-ink-3">{r.op}</span>
                )}
                {r.intra && (
                  <span className="rounded-pill bg-raised px-1.5 text-2xs text-ink-3">
                    {zh.anIntra}
                  </span>
                )}
              </span>
              <span className="block break-words font-mono text-xs text-ink-2 tabular-nums">
                {interactionGeometry(r)
                  .map(([n, v]) => `${n} ${v}`)
                  .join(" · ")}
              </span>
              <span className="sr-only">{r.passes ? zh.ixPasses : zh.ixFails}</span>
            </button>
            <QuoteButton
              onClick={() =>
                draft.insert(
                  withAnchor(
                    interactionQuote(r, inter),
                    node,
                    [r.d, r.a ? (isIdentityOp(r.op) ? r.a : `${r.a}(${String(r.op).replace(/\s+/g, "")})`) : undefined].filter(
                      (x): x is string => typeof x === "string" && x !== "",
                    ),
                  ),
                )
              }
            />
          </li>
        ))}
      </ul>
      {rows.length > ROWS_COLLAPSED && (
        <button
          type="button"
          className="mb-1.5 ml-3 text-2xs text-accent hover:underline"
          onClick={() => setAll((a) => !a)}
        >
          {all ? zh.anLess : `${zh.anMore} (${rows.length})`}
        </button>
      )}
    </div>
  );
}

function InteractionsSection({
  inter,
  node,
}: {
  inter: NonNullable<AnalysisResponse["interactions"]>;
  node: string;
}) {
  const [open, toggle] = useSection("an.interactions", true);
  const { state } = useCrystal();
  useEffect(() => {
    if (state.inspection?.node === node && !open) toggle();
  }, [state.inspection, node]);
  const kinds = INTERACTION_KINDS.filter((k) => (inter.unique[k]?.length ?? 0) > 0);
  const nPassing = Object.values(inter.counts.passing).reduce(
    (s, n) => s + (n ?? 0),
    0,
  );
  const meta = inter.counts.n_unique
    ? `${nPassing} / ${inter.counts.n_unique}`
    : zh.anNone;
  const hNote = zh.ixHSource[inter.h_source] ?? inter.h_source;
  return (
    <section data-stage="interactions" data-status="ready">
      {(Object.keys(inter.truncated).length > 0 || !inter.range.halo_sufficient) &&
        <div className="px-3 pt-2 text-xs text-warn">关系覆盖不完整 · {Object.keys(inter.truncated).length > 0 ? zh.anTruncated : zh.ixHaloShort}</div>}
      {inter.h_source === "unknown" && <div className="px-3 pt-2 text-xs text-warn">氢原子来源未知</div>}
      <SectionHeader
        title={zh.anInteractions}
        meta={meta}
        open={open}
        onToggle={toggle}
      />
      {open && (
        <>
          <div className="px-3 py-1.5 text-2xs text-ink-3">
            {inter.scope_note} · {hNote}
          </div>
          {!inter.range.halo_sufficient && (
            <div className="px-3 pb-1 text-2xs text-warn">
              {zh.ixHaloShort} {inter.range.halo_advised_A.toFixed(1)} Å
            </div>
          )}
          {kinds.length === 0 ? (
            <div className="px-3 pb-2 text-xs text-ink-3">{zh.anNoInteractions}</div>
          ) : (
            kinds.map((k) => (
              <KindBlock key={k} kind={k} rows={inter.unique[k] ?? []} inter={inter} node={node} />
            ))
          )}
        </>
      )}
    </section>
  );
}

// ----------------------------------------------------------------- pores

function dimLabel(v: VoidEntry): string {
  const d = v.dimensionality;
  if (typeof d !== "number") return "";
  return zh.anDim[d] ?? `${d}D`;
}

function fracText(f: [number, number, number] | undefined | null): string {
  return f ? `(${f.map((x) => x.toFixed(3)).join(", ")})` : "";
}

function PoreRow({ v, onQuote }: { v: VoidEntry; onQuote: () => void }) {
  const dirs = (v.directions ?? []).map((d) => `[${d.join(" ")}]`).join(" ");
  const facts: string[] = [];
  if (typeof v.lcd_A === "number") facts.push(`${zh.anLcd} ${v.lcd_A.toFixed(1)} Å`);
  if (typeof v.pld_A === "number") {
    const err = typeof v.pld_error_A === "number" ? ` ± ${v.pld_error_A.toFixed(2)}` : "";
    facts.push(`${zh.anPld} ${v.pld_A.toFixed(1)}${err} Å`);
  }
  if (v.pld_along) {
    const ax = (x: number | null) => (typeof x === "number" ? x.toFixed(1) : "—");
    facts.push(`${zh.anPldAlong} ${ax(v.pld_along.a)}/${ax(v.pld_along.b)}/${ax(v.pld_along.c)} Å`);
  }
  if (typeof v.grid_step_A === "number") facts.push(`±${v.grid_step_A.toFixed(2)} Å`);
  if (typeof v.electrons === "number") facts.push(`${Math.round(v.electrons)} ${zh.anElectrons}`);
  const centre =
    v.dimensionality === 0 && v.centre_frac
      ? `${zh.anCentroid} ${fracText(v.centre_frac)}`
      : v.inscribed_centre_frac
        ? `${zh.anCentre} ${fracText(v.inscribed_centre_frac)}`
        : "";
  return (
    <li className="group flex items-start gap-2 px-3 py-1 text-xs hover:bg-raised/50">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink">V{v.void}</span>
          <span className="font-mono text-ink-2 tabular-nums">
            {Math.round(v.volume_A3)} Å³
          </span>
          {dimLabel(v) && <span className="text-ink-2">{dimLabel(v)}</span>}
          {dirs && <span className="font-mono text-2xs text-ink-3">{dirs}</span>}
        </div>
        <div className="font-mono text-2xs text-ink-2 tabular-nums">
          {[...facts, centre].filter(Boolean).join(" · ")}
        </div>
      </div>
      <QuoteButton onClick={onQuote} />
    </li>
  );
}

function PoresSection({ pores, node }: { pores: NonNullable<AnalysisResponse["pores"]>; node: string }) {
  const draft = useComposerDraft();
  const [open, toggle] = useSection("an.pores", true);
  const voids = pores.voids ?? [];
  const pct =
    typeof pores.solvent_volume_pct_of_cell === "number"
      ? ` · ${pores.solvent_volume_pct_of_cell.toFixed(1)} %`
      : "";
  const meta = voids.length ? `${voids.length}${pct}` : zh.anNone;
  return (
    <section data-testid="analysis-pores" data-stage="pores" data-status="ready">
      <SectionHeader title={`${zh.anPores} · 每胞`} meta={meta} open={open} onToggle={toggle} />
      {open && (
        <>
          {voids.length === 0 ? (
            <div className="px-3 py-2 text-xs text-ink-3">{zh.anNoVoids}</div>
          ) : (
            <ul className="py-1">
              {voids.map((v) => (
                <PoreRow key={v.void} v={v} onQuote={() => draft.insert(withAnchor(poreQuote(v), node))} />
              ))}
            </ul>
          )}
          {pores.packing && (
            <div
              className="px-3 pb-1 font-mono text-2xs text-ink-2 tabular-nums"
              title={[pores.packing.reading, pores.packing.note].filter(Boolean).join("\n")}
            >
              {zh.anPacking} {pores.packing.packing_index_pct.toFixed(1)}
              {typeof pores.packing.packing_index_error_pct === "number"
                ? ` ± ${pores.packing.packing_index_error_pct.toFixed(1)}`
                : ""}{" "}
              % · {pores.packing.volume_per_non_h_atom_A3.toFixed(1)} {zh.anPerAtom}
            </div>
          )}
          {typeof pores.total_solvent_electrons_per_cell === "number" && (() => {
            const snap = pores.recorded?.total_solvent_electrons_per_cell;
            const snapNum = typeof snap === "number" ? snap : null;
            const rec = pores.total_solvent_electrons_per_cell;
            const unconverged = pores.bypass?.converged === false;
            const disagree = snapNum !== null && Math.abs(rec - snapNum) / Math.max(Math.abs(snapNum), 1e-9) > 0.2;
            return (
              <div
                className="px-3 pb-1 font-mono text-2xs text-ink-2 tabular-nums"
                title={unconverged ? zh.anElectronsUnconverged : disagree ? zh.anElectronsDisagree : undefined}
                data-recount={unconverged ? "unconverged" : disagree ? "disagree" : "ok"}
              >
                {zh.anElectronsRecomputed} {rec.toFixed(1)} {zh.anElectronsPerCell}
                {unconverged ? ` · ${zh.anElectronsUnconverged}` : ""}
                {snapNum !== null ? ` · ${zh.anElectronsSnapshot} ${snapNum.toFixed(1)} ${zh.anElectronsPerCell}` : ""}
                {disagree && !unconverged ? " ⚠" : ""}
              </div>
            );
          })()}
          <div className="border-b border-line/60 px-3 pb-2 text-2xs text-ink-3">
            {pores.params_source === "node" ? zh.anParamsNode : zh.anParamsDefaults}
            {pores.pore_note ? ` · ${pores.pore_note}` : ""}
            {pores.packing_note ? ` · ${pores.packing_note}` : ""}
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- guests

function GuestRow({ g, onQuote }: { g: GuestEntry; onQuote: () => void }) {
  const facts: string[] = [];
  if (g.void_id !== null && g.void_id !== undefined) facts.push(`V${g.void_id}`);
  if (g.host_fragment) facts.push(`${zh.anHost} ${g.host_fragment}`);
  if (typeof g.clearance_A === "number") facts.push(`${zh.anClearance} ${g.clearance_A.toFixed(2)} Å`);
  if (typeof g.d_to_inscribed_centre_A === "number")
    facts.push(`${zh.anToCentre} ${g.d_to_inscribed_centre_A.toFixed(1)} Å`);
  const c = g.nearest_host_contacts?.[0];
  if (c) facts.push(`${c.atom}···${c.host_atom} ${c.d.toFixed(2)} Å${isIdentityOp(c.sym) ? "" : ` (${c.sym})`}`);
  return (
    <li className="group flex items-start gap-2 px-3 py-1 text-xs hover:bg-raised/50">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink">{g.formula}</span>
          <span className="font-mono text-2xs text-ink-3">
            {g.fragment} · {g.copies} {zh.anGuestCopies}
          </span>
          <span className="rounded-pill bg-raised px-1.5 text-2xs text-ink-2">
            {zh.anSite[g.site] ?? g.site}
          </span>
          {g.straddles_regions && (
            <span className="text-2xs text-warn">{"跨区域"}</span>
          )}
        </div>
        <div className="font-mono text-2xs text-ink-2 tabular-nums">{facts.join(" · ")}</div>
      </div>
      <QuoteButton onClick={onQuote} />
    </li>
  );
}

function GuestsSection({ data }: { data: AnalysisResponse }) {
  const draft = useComposerDraft();
  const [open, toggle] = useSection("an.guests", true);
  const [showCriteria, setShowCriteria] = useState(false);
  const g = data.guests;
  const meta = g
    ? g.guests.length
      ? Object.entries(g.summary)
          .filter(([, n]) => n > 0)
          .map(([k, n]) => `${zh.anSite[k] ?? k} ${n}`)
          .join(" · ")
      : zh.anNone
    : zh.anPending;
  return (
    <section data-stage="guests" data-status={g ? "ready" : "error"}>
      <SectionHeader title={zh.anGuests} meta={meta} open={open} onToggle={toggle} />
      {open && !g && (
        <div className="px-3 py-2 text-xs text-ink-3">
          {zh.anGuestsFailed}
          {data.guests_error ? (
            <div className="font-mono text-2xs">{data.guests_error}</div>
          ) : null}
        </div>
      )}
      {open && g && (
        <>
          <div className="px-3 py-1.5 text-2xs text-ink-3">
            {g.host.selection_rule} ·{" "}
            {g.host.fragments.map((f) => `${f.key} ${f.formula}${f.dimensionality ? ` ${f.dimensionality}D` : ""}`).join("，")}
          </div>
          {g.guests.length === 0 ? (
            <div className="px-3 pb-2 text-xs text-ink-3">{zh.anNoGuests}</div>
          ) : (
            <ul className="pb-1">
              {g.guests.map((x) => (
                <GuestRow key={x.fragment} g={x} onQuote={() => draft.insert(withAnchor(guestQuote(x), data.node))} />
              ))}
            </ul>
          )}
          <button
            type="button"
            className="mb-1.5 ml-3 text-2xs text-accent hover:underline"
            onClick={() => setShowCriteria((s) => !s)}
          >
            {zh.anCriteria}
          </button>
          {showCriteria && (
            <dl className="border-b border-line/60 px-3 pb-2 text-2xs text-ink-3">
              {(["cage_cavity", "channel", "cavity", "interstitial"] as const).map((k) => (
                <div key={k} className="py-0.5">
                  <dt className="inline font-medium text-ink-2">{zh.anSite[k]}：</dt>
                  <dd className="inline">{String(g.criteria[k] ?? "")}</dd>
                </div>
              ))}
              <div className="pt-1 font-mono tabular-nums">
                probe {g.probe_A} Å · grid {g.grid_step_A} Å
                {typeof g.criteria.min_void_volume_A3 === "number"
                  ? ` · min ${g.criteria.min_void_volume_A3} Å³`
                  : ""}
              </div>
            </dl>
          )}
        </>
      )}
    </section>
  );
}

// -------------------------------------------------------------- topology

function labelsShort(labels: string[], n = 4): string {
  return labels.slice(0, n).join(" ") + (labels.length > n ? " …" : "");
}

function FragmentRow({ f, onQuote }: { f: FiniteFragment; onQuote: () => void }) {
  const facts: string[] = [];
  const c = f.largest_cycle;
  facts.push(c.size ? `${zh.anLargestCycle} ${c.size}${c.truncated ? "（截断）" : ""}` : zh.anNoRing);
  if (typeof f.shape?.sphericity === "number") facts.push(`${zh.anSphericity} ${f.shape.sphericity.toFixed(2)}`);
  if (f.shape?.aspect && f.shape.aspect.length === 2)
    facts.push(`${zh.anAspect} ${f.shape.aspect.map((x) => x.toFixed(2)).join(" / ")}`);
  if (typeof f.shape?.longest_axis_A === "number") facts.push(`${zh.anLongest} ${f.shape.longest_axis_A.toFixed(1)} Å`);
  return (
    <li className="group flex items-start gap-2 px-3 py-1 text-xs hover:bg-raised/50">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink">{f.fragment}</span>
          <span className="font-mono text-2xs text-ink-3">
            {f.n_atoms} · {f.role === "host" ? zh.anHostRole : zh.anGuestRole} · {f.copies} {zh.anGuestCopies} ·{" "}
            {labelsShort(f.asu_labels)}
          </span>
        </div>
        <div className="font-mono text-2xs text-ink-2 tabular-nums">{facts.join(" · ")}</div>
      </div>
      <QuoteButton onClick={onQuote} />
    </li>
  );
}

function NetsBlock({ t, node }: { t: AnalysisTopology; node: string }) {
  const draft = useComposerDraft();
  const nets = t.nets;
  return (
    <div className="group flex items-start gap-2 px-3 py-1.5 text-xs hover:bg-raised/50">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink">{zh.anNets}</span>
          {nets.n_nets === 0 ? (
            <span className="text-2xs text-ink-3">{zh.anNoNets}</span>
          ) : (
            <span className="font-mono text-2xs text-ink-2 tabular-nums">
              {nets.nets
                .map(
                  (n) =>
                    `${n.id}: ${zh.anDim[n.dimensionality] ?? `${n.dimensionality}D`}${n.direction ? ` [${n.direction.join(" ")}]` : ""} · ${n.n_atoms_p1}`,
                )
                .join("；")}
            </span>
          )}
          {nets.interpenetrated === true ? (
            <span className="rounded-pill bg-accent/12 px-1.5 text-2xs text-accent">{zh.anInterpenetratedYes}</span>
          ) : nets.interpenetrated === false && nets.symmetry_related ? (
            <span className="rounded-pill bg-raised px-1.5 text-2xs text-ink-2">{zh.anInterpenetratedNo}</span>
          ) : nets.symmetry_related ? (
            <span className="rounded-pill bg-raised px-1.5 text-2xs text-ink-2">{zh.anInterpenetrated}</span>
          ) : null}
        </div>
        {nets.relations.length > 0 && (
          <div className="font-mono text-2xs text-ink-2">
            {nets.relations
              .map(
                (r) =>
                  `${r.a}↔${r.b} ${relationName(r.relation)}${r.shift ? ` (${r.shift.join(", ")})` : ""}${r.op ? ` ${r.op}` : ""}`,
              )
              .join(" · ")}
          </div>
        )}
        {nets.interlocked_1d === true ? (
          <div className="text-2xs text-ink-2">{zh.anInterlockedYes}</div>
        ) : nets.symmetry_related_1d ? (
          <div className="text-2xs text-ink-3">{zh.anInterlocked}</div>
        ) : null}
        {nets.notes.map((n, i) => (
          <div key={i} className="text-2xs text-ink-3">
            {n}
          </div>
        ))}
      </div>
      <QuoteButton onClick={() => draft.insert(withAnchor(topologyQuote(t), node))} />
    </div>
  );
}

function SimplifiedNetBlock({ net }: { net: AnalysisTopology["simplified_net"] }) {
  const hist = Object.entries(net.node_connectivity_histogram)
    .map(([c, n]) => `${c}-c ×${n}`)
    .join(" ");
  return (
    <div className="px-3 py-1.5 text-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium text-ink">{zh.anSimplifiedNet}</span>
        {net.n_nodes_per_cell > 0 ? (
          <span className="font-mono text-2xs text-ink-2 tabular-nums">
            {net.n_nodes_per_cell} {zh.anNodes} / {net.n_edges_per_cell} {zh.anEdges} · {hist}
          </span>
        ) : (
          <span className="text-2xs text-ink-3">{net.note ?? zh.anNone}</span>
        )}
      </div>
      {net.n_nodes_per_cell > 0 && (
        <ul className="font-mono text-2xs text-ink-2">
          {net.nodes.slice(0, 12).map((n) => (
            <li key={n.id}>
              N{n.id} {zh.anNodeKind[n.kind] ?? n.kind} · {n.connectivity}-c · {labelsShort(n.atoms)}
              {n.periodic ? ` · ${zh.anRod}` : ""}
            </li>
          ))}
          {net.nodes.length > 12 && <li>… {net.nodes.length}</li>}
        </ul>
      )}
      <div className="text-2xs text-ink-3">{rcsrLine(net)}</div>
      {net.systre_error && (
        <div className="text-2xs text-warn">
          {zh.anSystreError}：{net.systre_error}
        </div>
      )}
      {net.confidence && <div className="text-2xs text-ink-3">{net.confidence}</div>}
    </div>
  );
}

/** `RCSR pcu` for one net, `RCSR pcu × 2（2 个分量）` when Systre named
 * several connected components (interpenetration), else the status. */
export function rcsrLine(net: AnalysisTopology["simplified_net"]): string {
  const syms = net.rcsr_symbols ?? [];
  if (syms.length > 1) {
    const uniq = Array.from(new Set(syms));
    return `RCSR ${uniq.join(" / ")} × ${syms.length}（${syms.length} ${zh.anRcsrComponents}）`;
  }
  return net.rcsr_symbol ? `RCSR ${net.rcsr_symbol}` : net.rcsr_status;
}

/** The engine's census of rings its ring finder cannot see (pipi / chpi
 * criteria blocks); an empty list when the block has none or is absent. */
export function ringsThroughSymmetry(crit: Record<string, unknown> | undefined): RingThroughSymmetry[] {
  const v = crit?.rings_closing_through_symmetry;
  if (!Array.isArray(v)) return [];
  return v.filter(
    (r): r is RingThroughSymmetry =>
      !!r && typeof r === "object" && typeof (r as RingThroughSymmetry).key === "string",
  );
}

function HelicesBlock({ helices }: { helices: AnalysisTopology["helices"] }) {
  return (
    <div className="px-3 py-1.5 text-xs">
      <span className="font-medium text-ink">{zh.anHelices}</span>{" "}
      {helices.length === 0 ? (
        <span className="text-2xs text-ink-3">{zh.anNoHelices}</span>
      ) : (
        <ul className="font-mono text-2xs text-ink-2 tabular-nums">
          {helices.map((h) => (
            <li key={h.fragment}>
              {h.fragment} {h.screw}{" "}
              {h.racemic ? zh.anRacemic : h.handedness ? (zh.anHand[h.handedness] ?? h.handedness) : zh.anAchiral} · [
              {h.chain_direction.join(" ")}] · {zh.anPitch} {h.pitch_A.toFixed(2)} Å · {labelsShort(h.asu_labels)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TopologySection({
  data,
  show,
}: {
  data: AnalysisResponse;
  show: Set<SectionId>;
}) {
  const draft = useComposerDraft();
  const [open, toggle] = useSection("an.topology", true);
  const [showDef, setShowDef] = useState(false);
  const t = data.topology;
  const meta = t
    ? t.nets.n_nets === 0
      ? zh.anNoNetsShort
      : `${t.nets.n_nets} ${zh.anNetsUnit}${
        t.nets.interpenetrated === true
          ? ` · ${zh.anInterpenetratedYes}`
          : t.nets.symmetry_related
            ? ` · ${t.nets.interpenetrated === false ? zh.anInterpenetratedNo : zh.anInterpenetrated}`
            : ""
      }`
    : zh.anPending;
  return (
    <section data-testid="analysis-topology" data-stage="topology" data-status={t ? "ready" : "error"}>
      <SectionHeader title={zh.anTopology} meta={meta} open={open} onToggle={toggle} />
      {open && !t && (
        <div className="px-3 py-2 text-xs text-ink-3">
          {zh.anTopologyFailed}
          {data.topology_error ? <div className="font-mono text-2xs">{data.topology_error}</div> : null}
        </div>
      )}
      {open && t && (
        <>
          {show.has("nets") && <NetsBlock t={t} node={data.node} />}
          {show.has("simplified_net") && <SimplifiedNetBlock net={t.simplified_net} />}
          {show.has("helices") && <HelicesBlock helices={t.helices} />}
          {show.has("fragments") && t.finite_fragments.length > 0 && (
            <div className="pb-1 text-xs">
              <div className="px-3 pt-1 font-medium text-ink">{zh.anFinite}</div>
              <ul>
                {t.finite_fragments.map((f) => (
                  <FragmentRow
                    key={f.fragment}
                    f={f}
                    onQuote={() => draft.insert(withAnchor(fragmentQuote(f), data.node, f.asu_labels.slice(0, 12)))}
                  />
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            className="mb-1.5 ml-3 text-2xs text-accent hover:underline"
            onClick={() => setShowDef((s) => !s)}
          >
            {zh.anDefinition}
          </button>
          {showDef && (
            <div className="border-b border-line/60 px-3 pb-2 text-2xs text-ink-3">
              <p>{t.nets.definition}</p>
              <p className="pt-1">{t.simplified_net.definition}</p>
              {t.helices[0]?.definition && <p className="pt-1">{t.helices[0].definition}</p>}
              {t.note && <p className="pt-1">{t.note}</p>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------- structure class

/** The owner's declaration of what the crystal is, with the system's
 * suggestion (and its basis) when nothing is declared yet. */
function StructureClassBar({
  data,
  cls,
  onChange,
  showAll,
  onToggleShowAll,
  hidden,
}: {
  data: AnalysisResponse;
  cls: StructureClass | null;
  onChange: (cls: StructureClass | null) => void;
  showAll: boolean;
  onToggleShowAll: () => void;
  hidden: string[];
}) {
  const suggestion = useMemo(() => data.topology ? suggestStructureClass(data) : null, [data]);
  return (
    <div className="border-b border-line px-3 py-1.5 text-2xs text-ink-3" data-testid="structure-class-bar">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-ink-2" title={zh.scTip}>
          {zh.scTitle}
        </span>
        <select
          aria-label={zh.scTitle}
          value={cls ?? ""}
          onChange={(e) => onChange(isStructureClass(e.target.value) ? e.target.value : null)}
          className="h-6 rounded-md border border-line bg-bg px-1.5 text-2xs text-ink"
        >
          <option value="">{zh.scAuto}</option>
          {STRUCTURE_CLASSES.map((c) => (
            <option key={c} value={c}>
              {structureClassLabel(c)}
            </option>
          ))}
        </select>
        {cls === null && suggestion !== null && (
          <>
            <span>
              {zh.scSuggested}：<span className="text-ink-2">{structureClassLabel(suggestion.cls)}</span>
            </span>
            <button
              type="button"
              onClick={() => onChange(suggestion.cls)}
              className="rounded-pill bg-raised px-2 py-0.5 text-2xs text-ink-2 transition-colors hover:text-ink"
            >
              {zh.scAdopt}
            </button>
          </>
        )}
        {hidden.length > 0 && (
          <button
            type="button"
            onClick={onToggleShowAll}
            className="ml-auto text-2xs text-accent hover:underline"
          >
            {showAll ? zh.scShowByClass : zh.scShowAll}
          </button>
        )}
      </div>
      {cls === null && suggestion !== null && (
        <div className="pt-0.5">
          {zh.scBasis}：{suggestion.basis.join("；")}
        </div>
      )}
      {hidden.length > 0 && !showAll && (
        <div className="pt-0.5">
          {zh.scHiddenPrefix}
          {hidden.join("、")}
        </div>
      )}
    </div>
  );
}

const SECTION_LABELS: Record<SectionId, () => string> = {
  interactions: () => zh.anInteractions,
  pores: () => zh.anPores,
  packing: () => zh.anPacking,
  guests: () => zh.anGuests,
  nets: () => zh.anNets,
  simplified_net: () => zh.anSimplifiedNet,
  helices: () => zh.anHelices,
  fragments: () => zh.anFinite,
};

const STAGE_ORDER: AnalysisStageName[] = ["interactions", "topology", "guests", "pores"];

function StageNotice({ name, stage }: { name: AnalysisStageName; stage?: AnalysisStage }) {
  const status = stage?.status ?? "waiting";
  return (
    <div className="border-b border-line px-3 py-3 text-xs text-ink-3"
      data-testid={`analysis-stage-${name}`} data-stage={name} data-status={status}>
      <div className="flex items-center gap-2">
        {status === "running" && <Spinner className="h-3 w-3" />}
        <span className="font-medium text-ink-2">{zh.analysisStageNames[name]}</span>
        <span>{zh.analysisStageStates[status]}</span>
      </div>
      {stage?.note && <p className="mt-1 leading-relaxed">{stage.note}</p>}
      {stage?.error && <details className="mt-1 text-2xs text-warn">
        <summary className="cursor-pointer">{zh.analysisErrorDetails}</summary>
        <div className="mt-1 break-words font-mono">{stage.error}</div>
      </details>}
    </div>
  );
}

function AnalysisProgress({ job, paused, stopping, onStop, onRetry }: {
  job: AnalysisJob; paused: boolean; stopping: boolean; onStop: () => void; onRetry: () => void;
}) {
  const running = analysisRunning(job);
  const ready = STAGE_ORDER.filter((name) => job.stages[name].status === "ready").length;
  return (
    <div className="border-b border-line bg-surface/50 px-3 py-2 text-2xs text-ink-2" data-testid="analysis-progress">
      <div className="flex flex-wrap items-center gap-2">
        <span className={running && !paused ? "shimmer-text" : ""}>
          {paused ? zh.analysisPaused : job.cache_hit ? zh.analysisCached : running ? zh.analysisWorking : zh.analysisFinished}
        </span>
        <span className="font-mono text-ink-3">{ready}/4 · {job.elapsed_s.toFixed(1)} s</span>
        {running && !paused && <button type="button" disabled={stopping} onClick={onStop}
          className="ml-auto rounded px-1.5 py-0.5 text-ink-2 hover:bg-raised disabled:opacity-50">{zh.analysisStop}</button>}
        {(paused || job.status === "partial" || job.status === "error" || job.status === "cancelled") &&
          <button type="button" onClick={onRetry} className="ml-auto rounded px-1.5 py-0.5 text-accent hover:bg-raised">{zh.anRetry}</button>}
      </div>
      {paused && <div className="mt-1 text-ink-3">{zh.analysisPauseNote}</div>}
      {job.status === "cancelling" && <div className="mt-1 text-ink-3">{zh.analysisCancelNote}</div>}
    </div>
  );
}

// ----------------------------------------------------------------- panel

export function AnalysisPanel() {
  const { state, project } = useCrystal();
  const wb = useWorkbench();
  const node = state.viewNode ?? state.activeNode;
  const { state: status, retry, stop, paused, stopping } = useAnalysis(project, node);
  const [showAll, setShowAll] = useState(false);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const declared: StructureClass | null = isStructureClass(wb.structureClass)
    ? wb.structureClass
    : null;

  if (!node) {
    return (
      <div className="flex flex-1 items-center justify-center text-xs text-ink-3">
        {zh.anNoNode}
      </div>
    );
  }
  if (status.kind === "loading" || status.kind === "idle" || (status.data !== null && status.data.node !== node)) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-xs text-ink-3">
        <Spinner />
        {zh.anLoading}
      </div>
    );
  }
  if (status.kind === "error") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <div className="text-xs text-danger">{zh.anError}</div>
        <div className="font-mono text-2xs text-ink-3">{status.message}</div>
        <button
          type="button"
          onClick={retry}
          className="h-7 rounded-lg border border-line px-3 text-xs text-ink-2 transition-colors hover:bg-raised"
        >
          {zh.anRetry}
        </button>
      </div>
    );
  }
  const data = status.data;
  if (data === null) return null;
  // Do not classify missing topology as a small molecule while it is still computing.
  const effective: StructureClass | null = declared ?? (data.topology ? suggestStructureClass(data).cls : null);
  const visible: Set<SectionId> = showAll || effective === null ? new Set(ALL_SECTION_IDS) : sectionsFor(effective);
  const hiddenWithContent = ALL_SECTION_IDS.filter(
    (id) => !visible.has(id) && sectionHasContent(id, data),
  ).map((id) => SECTION_LABELS[id]());
  const onChangeClass = (cls: StructureClass | null) => {
    setSaveNote(null);
    void wb.changeStructureClass(cls).then((err) => setSaveNote(err));
  };
  return (
    <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto [overflow-wrap:anywhere]" data-testid="analysis-panel">
      <AnalysisInspector />
      <details className="border-b border-line text-xs" open={state.selection?.atom.m || undefined}>
        <summary className="cursor-pointer px-3 py-2 font-medium text-ink">当前显示配位</summary>
        <CoordinationSection />
      </details>
      <div className="border-b border-line px-3 py-1.5 text-2xs text-ink-3">
        {zh.anScope} · <span className="font-mono">{data.node}</span>
      </div>
      {status.job && <AnalysisProgress job={status.job} paused={paused} stopping={stopping}
        onStop={() => void stop()} onRetry={retry} />}
      {status.message && <div className="border-b border-line px-3 py-2 text-xs text-warn">
        {status.message}<button type="button" onClick={retry} className="ml-2 text-accent">{zh.anRetry}</button>
      </div>}
      <details className="border-b border-line text-xs text-ink-3">
        <summary className="cursor-pointer px-3 py-2">显示区块{hiddenWithContent.length > 0 ? ` · 已折叠 ${hiddenWithContent.join("、")}` : ""}</summary>
        <StructureClassBar
          data={data}
          cls={declared}
          onChange={onChangeClass}
          showAll={showAll}
          onToggleShowAll={() => setShowAll((s) => !s)}
          hidden={hiddenWithContent}
        />
      </details>
      {saveNote && <div className="px-3 py-1 text-2xs text-warn">{saveNote}</div>}
      {(visible.has("interactions") || !data.interactions || state.inspection) && (data.interactions
        ? <InteractionsSection inter={data.interactions} node={data.node} />
        : <StageNotice name="interactions" stage={status.job?.stages.interactions} />)}
      {(visible.has("pores") || visible.has("packing") || !data.pores) && (data.pores
        ? <PoresSection pores={data.pores} node={data.node} />
        : <StageNotice name="pores" stage={status.job?.stages.pores} />)}
      {(visible.has("guests") || !data.guests) && (data.guests
        ? <GuestsSection data={data} />
        : <StageNotice name="guests" stage={status.job?.stages.guests} />)}
      {(visible.has("nets") || visible.has("simplified_net") || visible.has("helices") || visible.has("fragments") || !data.topology) &&
        (data.topology ? <TopologySection data={data} show={visible} />
          : <StageNotice name="topology" stage={status.job?.stages.topology} />)}
    </div>
  );
}

const ALL_SECTION_IDS: readonly SectionId[] = [
  "interactions",
  "pores",
  "packing",
  "guests",
  "nets",
  "simplified_net",
  "helices",
  "fragments",
];

/** Whether a section would show anything beyond "none" - used to tell the
 * user what the class gate is folding away. */
function sectionHasContent(id: SectionId, d: AnalysisResponse): boolean {
  const t = d.topology;
  switch (id) {
    case "interactions":
      return (d.interactions?.counts?.n_unique ?? 0) > 0;
    case "pores":
      return (d.pores?.voids?.length ?? 0) > 0;
    case "packing":
      return d.pores?.packing !== null && d.pores?.packing !== undefined;
    case "guests":
      return (d.guests?.guests.length ?? 0) > 0;
    case "nets":
      return (t?.nets.n_nets ?? 0) > 0;
    case "simplified_net":
      return (t?.simplified_net.n_nodes_per_cell ?? 0) > 0;
    case "helices":
      return (t?.helices.length ?? 0) > 0;
    case "fragments":
      return (t?.finite_fragments.length ?? 0) > 0;
    default:
      return false;
  }
}
