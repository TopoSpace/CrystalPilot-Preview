import { t } from "./i18n";
import type { NodeComparisonResponse, RefineNode, SceneAtom, SceneResponse } from "./wbTypes";

export function matchesComparison(data: NodeComparisonResponse, node: RefineNode, baseline: RefineNode): boolean {
  return data?.schema === 1 && data.node === node.id && data.baseline === baseline.id
    && Number.isFinite(data.project_revision)
    && ["compatible", "different", "unknown"].includes(data.frame?.status)
    && (["r1", "wr2", "goof"] as const).every((metric) =>
      ["comparable", "different", "unknown"].includes(data.metrics?.[metric]?.status)
      && Array.isArray(data.metrics?.[metric]?.reasons))
    && Array.isArray(data.differences) && Array.isArray(data.unknown_fields)
    && data.sources?.node?.node === node.id && data.sources?.baseline?.node === baseline.id
    && [data.sources.node, data.sources.baseline].every((source) => source.frame != null
      && typeof source.evidence?.reflection_recompute === "boolean")
    && (node.revision == null || data.sources.node.model_revision === node.revision)
    && (baseline.revision == null || data.sources.baseline.model_revision === baseline.revision);
}

export function comparableMetric(data: NodeComparisonResponse | null, metric: "r1" | "wr2" | "goof",
  node: RefineNode | undefined, baseline: RefineNode | undefined): boolean {
  if (!data || !node || !baseline || !matchesComparison(data, node, baseline)
    || data.metrics?.[metric]?.status !== "comparable"
    || !node.metrics_current || !baseline.metrics_current
    || [node[metric], baseline[metric]].some((value) => value == null || !Number.isFinite(value))) return false;
  return ([data.sources.node, data.sources.baseline]).every((source) => source.metrics_current
    && source.data_binding === "bound" && !!source.data_revision && Number.isFinite(source.model_revision)
    && source.model_revision !== null
    && source.metrics_source?.node === source.node && !!source.metrics_source.engine
    && source.metrics_source.model_revision === source.model_revision
    && source.metrics_source.data_revision === source.data_revision);
}

export function comparisonStatusLabel(status: string | undefined): string {
  return status === "comparable" ? t.cmpCondComparable : status === "different" ? t.cmpCondDifferent : t.cmpCondUnknown;
}

export interface ComparisonSelection {
  atom: SceneAtom;
  index: number;
}

const operator = (atom: SceneAtom): string => atom.sym
  ? (atom.symop ?? "").replace(/\s+/g, "")
  : "x,y,z";

/** Matching a label is not permission to substitute a different symmetry image. */
export function comparisonSelection(
  scene: SceneResponse,
  selected: ComparisonSelection | null,
): ComparisonSelection | null {
  if (!selected || !operator(selected.atom)) return null;
  const matches = scene.atoms.flatMap((atom, index) =>
    atom.flag !== "removed"
      && atom.label === selected.atom.label
      && (atom.part ?? 0) === (selected.atom.part ?? 0)
      && operator(atom) === operator(selected.atom)
      ? [{ atom, index }] : []);
  return matches.length === 1 ? matches[0] : null;
}

export function comparisonNumber(value: number | null | undefined, digits: number): string {
  return value != null && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

export function signedDifference(current: number | null | undefined, baseline: number | null | undefined, digits: number): string {
  if (current == null || baseline == null || !Number.isFinite(current) || !Number.isFinite(baseline)) return "—";
  const delta = current - baseline;
  if (Math.abs(delta) < 0.5 / 10 ** digits) return (0).toFixed(digits);
  return `${delta > 0 ? "+" : "−"}${Math.abs(delta).toFixed(digits)}`;
}

/** Keep camera events out of React state, with a bounded project-local cache. */
export class ComparisonCameras {
  private views = new Map<string, number[]>();

  get(key: string): number[] | undefined {
    return this.views.get(key)?.slice();
  }

  set(key: string, view: readonly number[]): void {
    if (!key || view.length < 8 || !view.every(Number.isFinite)) return;
    this.views.delete(key);
    this.views.set(key, [...view]);
    while (this.views.size > 8) this.views.delete(this.views.keys().next().value!);
  }
}
