import { findRenderedInteraction, overlayForInteraction } from "../../lib/analysisInspector";
import { t } from "../../lib/i18n";
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
  const message = !inspection ? t.crystal.inspAtomLocated
    : state.sceneStatus === "error" ? t.crystal.inspSceneError
    : waiting ? t.crystal.inspWaiting
    : !layerOn ? t.crystal.inspLayerOff
    : !match ? t.crystal.inspNoMatch
    : match.atomIndex === null ? t.crystal.inspCentroidOnly
    : match.row.boundary ? t.crystal.inspBoundary
    : t.crystal.inspLocated;
  return (
    <div className="border-b border-line bg-surface/60 px-3 py-2 text-xs" data-testid="analysis-inspector"
      data-node={state.viewNode} data-atom-label={atom?.label} data-symop={atom?.symop ?? (atom ? "x,y,z" : undefined)}
      data-match={match ? "rendered" : inspection ? "unavailable" : "atom"}>
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 break-words font-medium text-ink">
          {inspection ? interactionLabel(inspection.row) : atom?.label}
        </span>
        <button type="button" aria-label={t.crystal.inspClearAria} className="shrink-0 rounded px-2 text-ink-3 hover:bg-raised"
          onClick={() => inspection ? clearInspection() : select(null)}>×</button>
      </div>
      {atom && <div className="mt-1 break-words font-mono text-ink-2">{atom.label} · {atom.symop ?? "x,y,z"}</div>}
      <p role="status" className={`mt-1 leading-relaxed ${inspection && !match && !waiting ? "text-warn" : "text-ink-3"}`}>{message}</p>
      {hiddenEndpoint && <p className="mt-1 text-warn">{t.crystal.inspHiddenEndpoint}</p>}
      {match && <details className="mt-1 text-ink-3">
        <summary className="cursor-pointer">{t.crystal.inspSourceSummary}</summary>
        <div className="mt-1 break-words font-mono">{inspection?.node} · {t.crystal.inspFrom} {match.row.sym_i} · {t.crystal.inspTo} {match.row.sym}</div>
        <div className="mt-1">{t.crystal.inspInstanceCount(state.scene?.interactions?.counts.n_rows)}</div>
        {state.scene?.interactions?.truncated[match.row.kind] && <div className="text-warn">{t.crystal.inspKindTruncated}</div>}
        {state.scene?.interactions?.range.halo_sufficient === false && <div className="text-warn">{t.crystal.inspHaloShort}</div>}
      </details>}
    </div>
  );
}
