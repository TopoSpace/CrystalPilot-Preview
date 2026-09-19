import { useEffect, useState } from "react";
import { cx } from "../../lib/format";
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

const fieldNames: Record<string, string> = {
  data_revision: "反射数据", data_binding: "数据来源", engine: "精修引擎",
  weights: "权重", weighting: "权重", wght: "权重", h: "氢处理", hydrogen: "氢处理",
  mask: "掩膜", twin: "孪晶", cutoff: "反射范围", shel: "SHEL", omit: "OMIT",
  hklf: "HKLF", scale: "数据尺度", scale_k: "拟合尺度", cell: "晶胞",
  space_group: "空间群", wavelength: "波长", metrics_source: "指标来源",
  "cutoff.selected_reflections": "精修反射数", "cutoff.applied": "实际反射范围",
  "cutoff.requested": "请求反射范围", metric_definition: "指标定义", hydrogens: "氢处理",
};
const fieldLabel = (field: string) => fieldNames[field] ?? field;
const display = (value: unknown): string => value == null ? "未记录"
  : typeof value === "object" ? JSON.stringify(value) : String(value);

function Source({ node, source }: { node: RefineNode; source: NodeComparisonSource | undefined }) {
  const metricSource = source?.metrics_source;
  const conditions = source?.conditions;
  const cutoff = conditions?.cutoff;
  const selectedReflections = cutoff && "selected_reflections" in cutoff && typeof cutoff.selected_reflections === "number"
    ? cutoff.selected_reflections : null;
  return <div className="min-w-0 break-words" data-source-node={node.id}>
    <div className="font-mono">{node.id} · 修订 {source?.model_revision ?? node.revision ?? "未知"}</div>
    <div>{source?.data_binding === "structure_only" ? "仅结构" : source?.data_revision ? `数据 ${source.data_revision}` : "历史数据未绑定"}</div>
    <div>{metricSource ? `${metricSource.engine ?? "引擎未记录"} · ${metricSource.node}` : "指标来源未完整记录"}</div>
    {!node.metrics_current && <div>沿用指标，非本节点精修</div>}
    {conditions && <>
      <div>精修反射 {comparisonNumber(selectedReflections, 0)}</div>
      <div className="font-mono">WGHT {conditions.weights ? `${comparisonNumber(conditions.weights.a, 4)} ${comparisonNumber(conditions.weights.b, 4)}` : "未记录"}</div>
      <div>反射范围 {cutoff?.application === "ignored" ? "请求指令未应用" : cutoff?.application === "unknown" ? "应用情况未明"
        : Array.isArray(cutoff?.applied) ? cutoff.applied.join(" · ") || "无附加范围指令" : "未记录"}</div>
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
      `${item.id}：${METRICS.map(({ key, label, digits }) => `${label} ${comparisonNumber(item[key], digits)}`).join(" · ")}；模型 ASU ${item.n_atoms} 原子；数据 ${source?.data_revision ?? "未知"}；指标来源 ${source?.metrics_source?.node ?? "未完整记录"}${item.metrics_current ? "" : "（沿用）"}`,
      item.id,
    );
    draft.insert(`${describe(baseline, data?.sources.baseline)}\n${describe(node, data?.sources.node)}\n${METRICS.map(({ key, label }) => `${label}：${comparisonStatusLabel(statusFor(key))}`).join("；")}。${data?.frame.status === "compatible" ? "坐标系可共用镜头，但跨节点原子身份未确认" : data?.frame.status === "different" ? "坐标系不同，分别查看" : "坐标系未确认，分别查看"}。仅查看比较，未检出节点。`);
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
      <div role="group" aria-label="比较结构" className="flex min-w-0 rounded-lg bg-raised/70 p-0.5"
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
          aria-pressed={state.viewNode === item.id} aria-label={`查看${index === 0 ? "基线" : "对比"} ${item.id}`}
          onClick={() => comparisonSide(item.id)}
          className={cx("rounded-md px-2 py-1 font-mono", state.viewNode === item.id ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink")}>
          {chronological ? index === 0 ? "前" : "后" : index === 0 ? "基线" : "查看"} {item.id}
        </button>)}
      </div>
      <button type="button" aria-expanded={details} onClick={() => setDetails(!details)}
        className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">{comparisonStatusLabel(status)}</button>
      <div className="ml-auto flex items-center gap-1">
        <button type="button" onClick={quote} className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">引用对比</button>
        <button type="button" onClick={endComparison} className="rounded-md px-1.5 py-1 text-ink-2 hover:bg-raised">退出对比</button>
      </div>
    </div>
    <table className="mt-1 w-full table-fixed border-collapse tabular-nums" aria-label="节点数值对比">
      <thead><tr className="text-right text-ink-3"><th className="w-[19%] text-left font-normal">指标</th>
        <th className="font-mono font-normal">{baseline.id}</th><th className="font-mono font-normal">{node.id}</th>
        <th className="w-[25%] font-normal" title="查看节点减基线；条件未明或不同时仅显示中性数值">变化</th></tr></thead>
      <tbody>{METRICS.map(({ key, label, digits, ...options }) => {
        const comparable = comparableMetric(data, key, node, baseline);
        const delta = metricDelta(node[key], baseline[key], digits, "ideal" in options ? options.ideal : undefined,
          !node.metrics_current || !baseline.metrics_current, comparable);
        return <tr key={key} data-testid={`comparison-${key}`} data-comparable={comparable ? "true" : "false"}
          title={`${comparisonStatusLabel(statusFor(key))}${!node.metrics_current || !baseline.metrics_current ? " · 含沿用指标" : ""}`}>
          <th className="py-0.5 text-left font-normal text-ink-2">{label}</th>
          <td className="text-right font-mono text-ink">{comparisonNumber(baseline[key], digits)}</td>
          <td className="text-right font-mono text-ink">{comparisonNumber(node[key], digits)}</td>
          <td className={cx("text-right font-mono", delta.improved ? "text-ok" : delta.worsened ? "text-danger" : "text-ink-3")}>
            {delta.direction === "up" ? "▲" : delta.direction === "down" ? "▼" : ""}
            {signedDifference(node[key], baseline[key], digits)}
          </td>
        </tr>;
      })}
      <tr><th className="py-0.5 text-left font-normal text-ink-2">模型 ASU</th>
        <td className="text-right font-mono">{baseline.n_atoms}</td><td className="text-right font-mono">{node.n_atoms}</td>
        <td className="text-right font-mono text-ink-3">{signedDifference(node.n_atoms, baseline.n_atoms, 0)}</td></tr>
      </tbody>
    </table>
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-ink-3" aria-live="polite">
      <span title="绘制数不含已隐藏元素/PART及分数剖面外原子；相机遮挡不改变计数">{currentScene ? `${currentScene.node} · 绘制 ${drawnAtomCount(currentScene, state.hiddenElems, state.partFilter, state.slab)} / 场景 ${currentScene.meta.n_atoms} 原子${currentScene.meta.truncated ? "（已截断）" : ""}`
        : state.sceneStatus === "error" ? "结构加载失败" : `正在加载 ${state.viewNode}`}</span>
      {currentScene && <span>空间群 {currentScene.space_group}</span>}
      <span>{data?.frame.status === "compatible" ? "相机同步 · 选择独立" : data?.frame.status === "different" ? "坐标系不同，分别查看" : "坐标系未确认，分别查看"}</span>
    </div>
    {comparisonInfo.status === "error" && <div className="mt-1 text-ink-3">暂无法核对条件，仍可查看结构</div>}
    {details && <div className="mt-2 max-h-52 space-y-2 overflow-y-auto border-t border-line pt-2 text-ink-2">
      <div className="grid grid-cols-2 gap-3"><Source node={baseline} source={data?.sources.baseline} /><Source node={node} source={data?.sources.node} /></div>
      <div className="grid grid-cols-2 gap-3">
        {([data?.sources.baseline, data?.sources.node]).map((source, index) => <div key={index} className="min-w-0 break-words font-mono">
          <div>CELL {source?.frame.cell?.map((value) => comparisonNumber(value, 4)).join(" · ") ?? "未记录"}</div>
          <div>{source?.frame.space_group_operations?.length ?? "未知"} 个空间群操作</div>
        </div>)}
      </div>
      <table className="w-full table-fixed" aria-label="其它节点事实"><tbody>
        {([['参数', 'n_params'], ['残峰', 'diff_map_max'], ['残洞', 'diff_map_min']] as const).map(([label, key]) =>
          <tr key={key}><th className="text-left font-normal">{label}</th>
            <td className="text-right font-mono">{comparisonNumber(key === 'n_params' && (baseline[key] ?? 0) < 0 ? null : baseline[key], key === 'n_params' ? 0 : 3)}</td>
            <td className="text-right font-mono">{comparisonNumber(key === 'n_params' && (node[key] ?? 0) < 0 ? null : node[key], key === 'n_params' ? 0 : 3)}</td>
          </tr>)}
      </tbody></table>
      {METRICS.map(({ key, label }) => <div key={key}>{label} · {comparisonStatusLabel(statusFor(key))}
        {data?.metrics[key].reasons.length ? <span className="break-words"> · {data.metrics[key].reasons.map(fieldLabel).join("、")}</span> : null}</div>)}
      {(data?.differences ?? []).map((difference) => <div key={difference.field} className="break-words">
        {fieldLabel(difference.field)}：{display(difference.baseline)} → {display(difference.node)}
      </div>)}
      {!!data?.unknown_fields.length && <div className="break-words">未记录：{data.unknown_fields.map(fieldLabel).join("、")}</div>}
      {(!data || data.sources.node.data_binding === "legacy_unknown" || data.sources.baseline.data_binding === "legacy_unknown") &&
        <div>历史数据未绑定；不使用当前反射替算。
          <button type="button" className="ml-1 rounded px-1 text-accent hover:bg-raised" onClick={() => draft.insert(
            `请核对节点 ${baseline.id} 与 ${node.id} 的历史反射数据来源及逐指标比较条件。无法确认的绑定保持未知，不要把当前 HKL 自动绑定到历史节点；请先说明可验证的来源和需要我确认的内容。`)}>请求核对来源</button>
        </div>}
    </div>}
  </section>;
}
