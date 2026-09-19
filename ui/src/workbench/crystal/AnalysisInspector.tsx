import { findRenderedInteraction, overlayForInteraction } from "../../lib/analysisInspector";
import { interactionLabel } from "../../lib/interactions";
import { useCrystal } from "../../state/CrystalProvider";

/** The analysis product and the drawn scene have separate coverage contracts. */
export function AnalysisInspector() {
  const { state, clearInspection, select } = useCrystal();
  const inspection = state.inspection;
  const current = state.sceneNode === state.viewNode;
  if (inspection?.node !== state.viewNode && !state.selection) return null;
  const match = inspection && current && state.sceneStatus === "ok"
    ? findRenderedInteraction(state.scene, inspection.row, inspection.instance) : null;
  const atom = current ? state.selection?.atom : null;
  const waiting = state.sceneStatus === "loading" || !current;
  const layerOn = !inspection || state.overlays[overlayForInteraction(inspection.row.kind)];
  const hiddenEndpoint = match && [match.row.ai, match.row.bi].some((index) => {
    const endpoint = index === null ? null : state.scene?.atoms[index];
    return endpoint && (state.hiddenElems.includes(endpoint.elem)
      || (state.partFilter !== null && (endpoint.part ?? 0) !== 0 && endpoint.part !== state.partFilter));
  });
  const message = !inspection ? "已定位当前显示原子；配位数来自本次显示的成键列表。"
    : state.sceneStatus === "error" ? "显示范围加载失败；未把分析行绑定到旧场景。"
    : waiting ? "正在载入相互作用显示实例…"
    : !layerOn ? "该关系图层已关闭；再次选择表格行可重新显示。"
    : !match ? "当前范围未找到该实例（可能在范围外或被预算截断）；未替选 ASU 原子。可在结构范围菜单中调整。"
    : match.atomIndex === null ? "已显示质心连线；数据未提供端点原子映射，未猜选环原子。"
    : match.row.boundary ? "已定位范围内端点；另一端在显示范围外。"
    : "已定位实际端点；分析表按对称独立关系计数，不随超胞复制。";
  return (
    <div className="border-b border-line bg-surface/60 px-3 py-2 text-xs" data-testid="analysis-inspector"
      data-node={state.viewNode} data-atom-label={atom?.label} data-symop={atom?.symop ?? (atom ? "x,y,z" : undefined)}
      data-match={match ? "rendered" : inspection ? "unavailable" : "atom"}>
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 break-words font-medium text-ink">
          {inspection ? interactionLabel(inspection.row) : atom?.label}
        </span>
        <button type="button" aria-label="清除检查选择" className="shrink-0 rounded px-2 text-ink-3 hover:bg-raised"
          onClick={() => inspection ? clearInspection() : select(null)}>×</button>
      </div>
      {atom && <div className="mt-1 break-words font-mono text-ink-2">{atom.label} · {atom.symop ?? "x,y,z"}</div>}
      <p role="status" className={`mt-1 leading-relaxed ${inspection && !match && !waiting ? "text-warn" : "text-ink-3"}`}>{message}</p>
      {hiddenEndpoint && <p className="mt-1 text-warn">端点元素或 PART 已隐藏，关系线不可见；定位标记仍使用实际原子坐标。</p>}
      {match && <details className="mt-1 text-ink-3">
        <summary className="cursor-pointer">显示实例与来源</summary>
        <div className="mt-1 break-words font-mono">{inspection?.node} · 起点 {match.row.sym_i} · 终点 {match.row.sym}</div>
        <div className="mt-1">{state.scene?.interactions?.counts.n_rows} 条显示实例（非每胞数量）</div>
        {state.scene?.interactions?.truncated[match.row.kind] && <div className="text-warn">此类显示关系已被预算截断</div>}
        {state.scene?.interactions?.range.halo_sufficient === false && <div className="text-warn">边界搜索范围不足</div>}
      </details>}
    </div>
  );
}
