import { useEffect, useState } from "react";
import { getRefineComparison } from "../lib/wbApi";
import type { NodeComparisonResponse, RefineNode } from "../lib/wbTypes";
import { matchesComparison } from "../lib/structureComparison";

export interface NodeComparisonResult {
  data: NodeComparisonResponse | null;
  status: "idle" | "loading" | "ok" | "error";
}

export function useNodeComparison(project: string | null, node: RefineNode | undefined,
  baseline: RefineNode | undefined): NodeComparisonResult {
  const key = JSON.stringify([project, node?.id, baseline?.id]);
  const version = JSON.stringify([node?.revision, node?.comparison_source, baseline?.revision, baseline?.comparison_source]);
  const [result, setResult] = useState<NodeComparisonResult & { key: string; version: string }>({
    key: "", version: "", data: null, status: "idle",
  });
  useEffect(() => {
    if (!project || !node || !baseline || node.id === baseline.id) return;
    const controller = new AbortController();
    setResult({ key, version, data: null, status: "loading" });
    getRefineComparison(project, node.id, baseline.id, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!matchesComparison(data, node, baseline)) throw new Error("Comparison source mismatch");
        setResult({ key, version, data, status: "ok" });
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ key, version, data: null, status: "error" });
      });
    return () => controller.abort();
    // The source version, not freshly allocated nodes from polling, defines the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);
  if (!project || !node || !baseline || node.id === baseline.id) return { data: null, status: "idle" };
  return result.key === key && result.version === version ? result : { data: null, status: "loading" };
}
