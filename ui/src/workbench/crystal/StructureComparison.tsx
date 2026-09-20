import { useEffect, useState } from "react";
import { cx } from "../../lib/format";
import { t } from "../../lib/i18n";
import { metricDelta } from "../../lib/metricDelta";
import { comparableMetric, comparisonNumber, comparisonStatusLabel, signedDifference } from "../../lib/structureComparison";
import { withAnchor } from "../../lib/quote";
import type { NodeComparisonSource, RefineNode } from "../../lib/wbTypes";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useCrystal } from "../../state/CrystalProvider";
import { drawnAtomCount } from "./viewerVisibility";

const METRICS = [
  { key: "r1", label: "R1", digits: 4 },
  { key: "wr2", label: "wR2", digits: 4 },
  { key: "goof", label: "GooF", digits: 3, ideal: 1 },
] as const;

const fieldNames: Record<string, string> = t.crystal.cmpFieldNames;
const fieldLabel = (field: string) => fieldNames[field] ?? field;
const display = (value: unknown): string => value == null ? t.crystal.cmpNotRecorded
  : typeof value === "object" ? JSON.stringify(value) : String(value);

function Source({ node, source }: { node: RefineNode; source: NodeComparisonSource | undefined }) {
  const metricSource = source?.metrics_source;
  const conditions = source?.conditions;
  const cutoff = conditions?.cutoff;
  const selectedReflections = cutoff && "selected_reflections" in cutoff && typeof cutoff.selected_reflections === "number"
    ? cutoff.selected_reflections : null;
  return <div className="min-w-0 break-words" data-source-node={node.id}>
    <div className="font-mono">{node.id} · {t.crystal.cmpRevision} {source?.model_revision ?? node.revision ?? t.crystal.cmpUnknown}</div>
    <div>{source?.data_binding === "structure_only" ? t.crystal.cmpStructureOnly : source?.data_revision ? t.crystal.cmpData(source.data_revision) : t.crystal.cmpLegacyUnbound}</div>
    <div>{metricSource ? `${metricSource.engine ?? t.crystal.cmpEngineNotRecorded} · ${metricSource.node}` : t.crystal.cmpMetricSourceIncomplete}</div>
    {!node.metrics_current && <div>{t.crystal.cmpInheritedNote}</div>}
    {conditions && <>
      <div>{t.crystal.cmpRefinedReflections} {comparisonNumber(selectedReflections, 0)}</div>
      <div className="font-mono">WGHT {conditions.weights ? `${comparisonNumber(conditions.weights.a, 4)} ${comparisonNumber(conditions.weights.b, 4)}` : t.crystal.cmpNotRecorded}</div>
      <div>{t.crystal.cmpCutoff} {cutoff?.application === "ignored" ? t.crystal.cmpCutoffIgnored : cutoff?.application === "unknown" ? t.crystal.cmpCutoffUnknown
        : Array.isArray(cutoff?.applied) ? cutoff.applied.join(" · ") || t.crystal.cmpCutoffNone : t.crystal.cmpNotRecorded}</div>
    </>}
  </div>;
}

export function StructureComparison() {
  const { state, comparisonInfo, comparisonSide, endComparison, sceneReady } = useCrystal();
  const draft = useComposerDraft();
  const [details, setDetails] = useState(false);
  const pair = state.comparison;
  useEffect(() => setDetails(false), [pair?.node, pair?.baseline]);
  if (!pair) return null;
  const node = state.nodes.find((item) => item.id === pair.node);
  const baseline = state.nodes.find((item) => item.id === pair.baseline);
  if (!node || !baseline) return null;
  const data = comparisonInfo.data;
  const statusFor = (key: "r1" | "wr2" | "goof") => data?.metrics[key].status === "comparable"
    && !comparableMetric(data, key, node, baseline) ? "unknown" : data?.metrics[key].status ?? "unknown";
  const statuses = METRICS.map(({ key }) => statusFor(key));
  const status = statuses.every((value) => value === "comparable") ? "comparable"
    : statuses.includes("different") ? "different" : "unknown";
  let ancestor = node.parent;
  const visited = new Set<string>();
  while (ancestor && ancestor !== baseline.id && !visited.has(ancestor)) {
    visited.add(ancestor);
    ancestor = state.nodes.find((item) => item.id === ancestor)?.parent ?? null;
  }
  const chronological = ancestor === baseline.id;
  const currentScene = sceneReady ? state.scene : null;
  const quote = () => {
    const describe = (item: RefineNode, source: NodeComparisonSource | undefined) => withAnchor(
      t.crystal.cmpQuoteNode(
        item.id,
        METRICS.map(({ key, label, digits }) => `${label} ${comparisonNumber(item[key], digits)}`).join(" · "),
        item.n_atoms,
        source?.data_revision ?? t.crystal.cmpUnknown,
        source?.metrics_source?.node ?? t.crystal.cmpNotFullyRecorded,
        !item.metrics_current,
      ),
      item.id,
    );
    const frameNote = data?.frame.status === "compatible" ? t.crystal.cmpFrameCompatibleQuote
      : data?.frame.status === "different" ? t.crystal.cmpFrameDifferent : t.crystal.cmpFrameUnknown;
    draft.insert(t.crystal.cmpQuote(
      describe(baseline, data?.sources.baseline),
      describe(node, data?.sources.node),
      METRICS.map(({ key, label }) => t.crystal.cmpQuoteMetric(label, comparisonStatusLabel(statusFor(key)))),
      frameNote,
    ));
  };
  return <section data-testid="structure-comparison" data-node={node.id} data-baseline={baseline.id}
    data-comparability={status} className="shrink-0 border-b border-line px-3 py-2 text-sm"
    onKeyDown={(event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault(); event.stopPropagation();
      if (details) setDetails(false);
      else endComparison();
    }}>
    <div className="flex flex-wrap items-center gap-1.5">
      <div role="group" aria-label={t.crystal.cmpGroupAria} className="flex min-w-0 rounded-lg bg-raised/70 p-0.5"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
          const focused = buttons.indexOf(event.target as HTMLButtonElement);
          const index = focused >= 0 ? focused : state.viewNode === baseline.id ? 0 : 1;
          const next = event.key === "Home" ? 0 : event.key === "End" ? 1
            : (index + (event.key === "ArrowRight" ? 1 : -1) + 2) % 2;
          comparisonSide(next === 0 ? baseline.id : node.id);
          buttons[next]?.focus();
        }}>
        {([baseline, node]).map((item, index) => <button key={item.id} type="button"
          aria-pressed={state.viewNode === item.id} aria-label={t.crystal.cmpViewAria(index === 0, item.id)}
          onClick={() => comparisonSide(item.id)}
          className={cx("rounded-md px-2 py-1 font-mono", state.viewNode === item.id ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink")}>
          {chronological ? index === 0 ? t.crystal.cmpBefore : t.crystal.cmpAfter : index === 0 ? t.crystal.cmpBaseline : t.crystal.cmpView} {item.id}
        </button>)}
      </div>
      <button type="button" aria-expanded={details} onClick={() => setDetails(!details)}
        className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">{comparisonStatusLabel(status)}</button>
      <div className="ml-auto flex items-center gap-1">
        <button type="button" onClick={quote} className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">{t.crystal.cmpQuoteBtn}</button>
        <button type="button" onClick={endComparison} className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">{t.crystal.cmpExitBtn}</button>
      </div>
    </div>
    <table className="mt-1 w-full table-fixed border-collapse tabular-nums" aria-label={t.crystal.cmpTableAria}>
      <thead><tr className="text-right text-ink-3"><th className="w-[19%] text-left font-normal">{t.crystal.cmpMetricCol}</th>
        <th className="font-mono font-normal">{baseline.id}</th><th className="font-mono font-normal">{node.id}</th>
        <th className="w-[25%] font-normal" title={t.crystal.cmpChangeTip}>{t.crystal.cmpChangeCol}</th></tr></thead>
      <tbody>{METRICS.map(({ key, label, digits, ...options }) => {
        const comparable = comparableMetric(data, key, node, baseline);
        const delta = metricDelta(node[key], baseline[key], digits, "ideal" in options ? options.ideal : undefined,
          !node.metrics_current || !baseline.metrics_current, comparable);
        return <tr key={key} data-testid={`comparison-${key}`} data-comparable={comparable ? "true" : "false"}
          title={`${comparisonStatusLabel(statusFor(key))}${!node.metrics_current || !baseline.metrics_current ? t.crystal.cmpInheritedSuffix : ""}`}>
          <th className="py-0.5 text-left font-normal text-ink-2">{label}</th>
          <td className="text-right font-mono text-ink">{comparisonNumber(baseline[key], digits)}</td>
          <td className="text-right font-mono text-ink">{comparisonNumber(node[key], digits)}</td>
          <td className={cx("text-right font-mono", delta.improved ? "text-ok" : delta.worsened ? "text-danger" : "text-ink-3")}>
            {delta.direction === "up" ? "▲" : delta.direction === "down" ? "▼" : ""}
            {signedDifference(node[key], baseline[key], digits)}
          </td>
        </tr>;
      })}
      <tr><th className="py-0.5 text-left font-normal text-ink-2">{t.crystal.cmpModelAsu}</th>
        <td className="text-right font-mono">{baseline.n_atoms}</td><td className="text-right font-mono">{node.n_atoms}</td>
        <td className="text-right font-mono text-ink-3">{signedDifference(node.n_atoms, baseline.n_atoms, 0)}</td></tr>
      </tbody>
    </table>
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-ink-3" aria-live="polite">
      <span title={t.crystal.cmpDrawnTip}>{currentScene ? t.crystal.cmpDrawnLine(currentScene.node, drawnAtomCount(currentScene, state.hiddenElems, state.partFilter, state.slab), currentScene.meta.n_atoms, currentScene.meta.truncated)
        : state.sceneStatus === "error" ? t.crystal.cmpSceneFailed : t.crystal.loadingNode(state.viewNode)}</span>
      {currentScene && <span>{t.dataSpaceGroup} {currentScene.space_group}</span>}
      <span>{data?.frame.status === "compatible" ? t.crystal.cmpFrameCompatible : data?.frame.status === "different" ? t.crystal.cmpFrameDifferent : t.crystal.cmpFrameUnknown}</span>
    </div>
    {comparisonInfo.status === "error" && <div className="mt-1 text-ink-3">{t.crystal.cmpConditionsUnavailable}</div>}
    {details && <div className="mt-2 max-h-52 space-y-2 overflow-y-auto border-t border-line pt-2 text-ink-2">
      <div className="grid grid-cols-2 gap-3"><Source node={baseline} source={data?.sources.baseline} /><Source node={node} source={data?.sources.node} /></div>
      <div className="grid grid-cols-2 gap-3">
        {([data?.sources.baseline, data?.sources.node]).map((source, index) => <div key={index} className="min-w-0 break-words font-mono">
          <div>CELL {source?.frame.cell?.map((value) => comparisonNumber(value, 4)).join(" · ") ?? t.crystal.cmpNotRecorded}</div>
          <div>{t.crystal.cmpSymops(source?.frame.space_group_operations?.length ?? t.crystal.cmpUnknown)}</div>
        </div>)}
      </div>
      <table className="w-full table-fixed" aria-label={t.crystal.cmpFactsAria}><tbody>
        {([[t.paramsLabel, 'n_params'], [t.headerPeak, 'diff_map_max'], [t.headerHole, 'diff_map_min']] as const).map(([label, key]) =>
          <tr key={key}><th className="text-left font-normal">{label}</th>
            <td className="text-right font-mono">{comparisonNumber(key === 'n_params' && (baseline[key] ?? 0) < 0 ? null : baseline[key], key === 'n_params' ? 0 : 3)}</td>
            <td className="text-right font-mono">{comparisonNumber(key === 'n_params' && (node[key] ?? 0) < 0 ? null : node[key], key === 'n_params' ? 0 : 3)}</td>
          </tr>)}
      </tbody></table>
      {METRICS.map(({ key, label }) => <div key={key}>{label} · {comparisonStatusLabel(statusFor(key))}
        {data?.metrics[key].reasons.length ? <span className="break-words"> · {data.metrics[key].reasons.map(fieldLabel).join(t.crystal.listSeparator)}</span> : null}</div>)}
      {(data?.differences ?? []).map((difference) => <div key={difference.field} className="break-words">
        {t.crystal.cmpDiffLine(fieldLabel(difference.field), display(difference.baseline), display(difference.node))}
      </div>)}
      {!!data?.unknown_fields.length && <div className="break-words">{t.crystal.cmpUnrecordedPrefix}{data.unknown_fields.map(fieldLabel).join(t.crystal.listSeparator)}</div>}
      {(!data || data.sources.node.data_binding === "legacy_unknown" || data.sources.baseline.data_binding === "legacy_unknown") &&
        <div>{t.crystal.cmpLegacyNote}
          <button type="button" className="ml-1 rounded px-1 text-accent hover:bg-raised" onClick={() => draft.insert(
            t.crystal.cmpRequestVerify(baseline.id, node.id))}>{t.crystal.cmpRequestVerifyBtn}</button>
        </div>}
    </div>}
  </section>;
}
