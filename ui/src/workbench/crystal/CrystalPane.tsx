/** Crystal pane body (P2): history banner + structure header + tab content.
 * 结构 tab = the 3Dmol canvas with every control floating on it
 * (CrystalToolbar) plus the atom / peak selection cards; other tabs
 * delegate to NodeTreePanel / MetricsPanel / ArtifactsPanel. */
import { Fragment, lazy, Suspense, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { AlertBanner, Spinner } from "../../components/ui";
import { adpAnomalies, adpReasons } from "../../lib/adp";
import { measureReadout } from "../../lib/measure";
import {
  atomQuote,
  frameQuote,
  measureQuote,
  peakQuote,
  voidQuote,
  withAnchor,
} from "../../lib/quote";
import { ORIGIN_TILES } from "../../lib/tiles";
import { getRefineTopology } from "../../lib/wbApi";
import { cx } from "../../lib/format";
import { t } from "../../lib/i18n";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useCrystal } from "../../state/CrystalProvider";
import type {
  InteractionKind,
  InteractionRow,
  NetEdge,
  NetNode,
  PeakEntry,
  RefineNode,
  SceneInteractions,
} from "../../lib/wbTypes";
import {
  criteriaSummary,
  interactionGeometry,
  interactionLabel,
  interactionQuote,
  isIdentityOp,
} from "../../lib/interactions";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { activeLayerLabels, ExtentMenu, FloatingBar } from "./CrystalToolbar";
import { extentLabel } from "./extent";
import { MetricsPanel } from "./MetricsPanel";
import { NodeTreePanel } from "./NodeTreePanel";
import { StructureHeader } from "./StructureHeader";
import { StructureComparison } from "./StructureComparison";
import { AnalysisPanel } from "./AnalysisPanel";
import { ValidationPanel } from "./ValidationPanel";
import { overlayCoverage } from "./viewerLimits";
import { useSection } from "./useSection";

const CrystalViewer = lazy(() => import("./CrystalViewer"));

export type CrystalTabId =
  | "structure"
  | "analysis"
  | "nodes"
  | "metrics"
  | "validation"
  | "artifacts";

// ------------------------------------------------------------- history banner

function HistoryBanner() {
  const { state, followLatest } = useCrystal();
  if (state.follow || state.viewNode === null || state.comparison) return null;
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-warn/30 bg-warn/10 px-3 py-1.5 text-xs text-warn">
      <span className="min-w-0 truncate">
        {t.historyViewingPrefix}{" "}
        <span className="font-mono font-medium">{state.viewNode}</span>
      </span>
      <button
        type="button"
        onClick={followLatest}
        className="ml-auto shrink-0 rounded-pill border border-warn/40 px-2 py-0.5 font-medium transition-colors hover:bg-warn/15"
      >
        {t.backToLatest}
      </button>
    </div>
  );
}


// -------------------------------------------------------------- selection card

function SelectionCard({ onCenter }: { onCenter: () => void }) {
  const { state, select, sceneReady } = useCrystal();
  const draft = useComposerDraft();
  const sel = state.selection;
  if (!sel || !sceneReady) return null;
  const a = sel.atom;

  return (
    <div data-testid="atom-selection" data-node={state.sceneNode} data-label={a.label} data-symop={a.symop ?? "x,y,z"}
      className="absolute bottom-12 left-2.5 z-10 w-56 rounded-card border border-line bg-bg/95 p-2.5 shadow-lg backdrop-blur-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm font-semibold text-ink">
          {a.label}
        </span>
        <span className="text-2xs text-ink-3">{a.elem}</span>
        {a.sym && <span className="text-2xs text-ink-3">{t.crystal.paneSymmetryCopy}</span>}
        <button
          type="button"
          title={t.selCenterTip}
          onClick={onCenter}
          className="ml-auto -mt-0.5 h-5 rounded px-1.5 text-2xs text-ink-3 hover:bg-raised hover:text-ink"
        >
          {t.selCenter}
        </button>
        <button
          type="button"
          aria-label={t.cancel}
          onClick={() => select(null)}
          className="-mt-0.5 flex h-5 w-5 items-center justify-center rounded text-ink-3 hover:bg-raised hover:text-ink"
        >
          ×
        </button>
      </div>
      <div className="mt-1 flex gap-3 font-mono text-2xs text-ink-2 tabular-nums">
        <span>
          U<sub>eq</sub> {a.adp_known === false || a.u_eq === null ? "—" : a.u_eq.toFixed(4)}
        </span>
        <span>
          {t.selOccupancy} {a.occ.toFixed(2)}
        </span>
      </div>
      {a.symop && (
        <div
          className="mt-0.5 truncate font-mono text-2xs text-ink-3"
          title={a.symop}
        >
          {t.selSymop} {a.symop}
        </div>
      )}
      {adpReasons(a).map((reason) => (
        <div key={reason} className="mt-0.5 text-2xs text-warn">
          ⚠ {reason}
        </div>
      ))}
      <button
        type="button"
        onClick={() => {
          draft.insert(atomQuote(a, adpReasons(a), state.scene?.node,
            state.nodes.find((node) => node.id === state.scene?.node)?.structure_only));
          select(null);
        }}
        className="mt-2 h-6 w-full rounded-lg bg-accent/10 px-2 text-2xs font-medium text-accent transition-colors hover:bg-accent/15"
      >
        {t.selQuote}
      </button>
    </div>
  );
}

// ----------------------------------------------------------- interaction card

/** Clicked interaction segment: label line, the kind's own geometry, the
 * operator that places an off-screen partner, the H-source caveat, the rule
 * set it was judged by, and quote-to-chat. Numbers never appear without
 * their rule (plan §2 principle 1). */
function InteractionCard({
  row,
  meta,
  onClose,
}: {
  row: InteractionRow;
  meta: SceneInteractions;
  onClose: () => void;
}) {
  const draft = useComposerDraft();
  const { state } = useCrystal();
  const kindName = t.ixKind[row.kind] ?? row.kind;
  const geom = interactionGeometry(row);
  const crit = criteriaSummary(meta.criteria[row.kind]);
  const showH = row.kind === "hbond" || row.kind === "chx" || row.kind === "chpi";
  const trunc = meta.truncated[row.kind];
  return (
    <div className="absolute bottom-12 left-2.5 z-10 w-64 rounded-card border border-line bg-bg/95 p-2.5 shadow-lg backdrop-blur-sm">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold text-ink">{kindName}</span>
        <span
          className={cx(
            "rounded-pill px-1.5 text-2xs font-medium",
            row.passes ? "bg-ok/12 text-ok" : "bg-warn/12 text-warn",
          )}
        >
          {row.passes ? t.ixPasses : t.ixFails}
        </span>
        <button
          type="button"
          aria-label={t.cancel}
          onClick={onClose}
          className="ml-auto -mt-0.5 flex h-5 w-5 items-center justify-center rounded text-ink-3 hover:bg-raised hover:text-ink"
        >
          ×
        </button>
      </div>
      <div className="mt-1 font-mono text-xs text-ink">{interactionLabel(row)}</div>
      <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 font-mono text-2xs text-ink-2 tabular-nums">
        {geom.map(([n, v]) => (
          <Fragment key={n}>
            <span className="text-ink-3">{n}</span>
            <span className="text-right">{v}</span>
          </Fragment>
        ))}
      </div>
      {(row.boundary || !isIdentityOp(row.sym)) && (
        <div className="mt-1 truncate font-mono text-2xs text-ink-3" title={row.sym}>
          {row.boundary ? `${t.ixBoundary} · ` : ""}
          {t.ixSymop} {row.sym}
        </div>
      )}
      {showH && (
        <div className="mt-0.5 text-2xs text-ink-3">
          {t.ixHSource[meta.h_source] ?? meta.h_source}
        </div>
      )}
      {crit && (
        <div className="mt-0.5 text-2xs text-ink-3">
          {t.ixCriteria}{t.colon}{crit}
        </div>
      )}
      {!meta.range.halo_sufficient && (
        <div className="mt-0.5 text-2xs text-warn">⚠ {t.ixHaloShort}</div>
      )}
      {trunc && (
        <div className="mt-0.5 text-2xs text-warn">
          ⚠ {t.ixTruncated} {trunc.cap} / {trunc.found}
        </div>
      )}
      <button
        type="button"
        onClick={() => {
          draft.insert(withAnchor(interactionQuote(row, meta), state.scene?.node));
          onClose();
        }}
        className="mt-2 h-6 w-full rounded-lg bg-accent/10 px-2 text-2xs font-medium text-accent transition-colors hover:bg-accent/15"
      >
        {t.ixQuote}
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ peak card

/** Clicked Q-peak card: height + nearest-atom context + quote-to-chat.
 * The quote cites position/height/nearest atom, NOT the bare ordinal - the
 * agent-side session peak table is computed independently and its indices
 * may differ (peaks.json note); agents re-run inspect_map to align. */
function PeakCard({
  sel,
  onClose,
}: {
  sel: { peak: PeakEntry; index: number };
  onClose: () => void;
}) {
  const draft = useComposerDraft();
  const { state } = useCrystal();
  const { peak, index } = sel;
  const near =
    peak.nearest_atom !== null && peak.nearest_d !== null
      ? `${t.peakNearest} ${peak.nearest_atom}${t.paren(`${peak.nearest_d.toFixed(2)} Å`)}`
      : null;
  return (
    <div className="absolute bottom-12 left-2.5 z-10 w-60 rounded-card border border-line bg-bg/95 p-2.5 shadow-lg backdrop-blur-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm font-semibold text-[#f97316]">
          Q{index + 1}
        </span>
        <span className="font-mono text-2xs text-ink-2 tabular-nums">
          {peak.height.toFixed(2)} eÅ⁻³
        </span>
        <button
          type="button"
          aria-label={t.cancel}
          onClick={onClose}
          className="ml-auto -mt-0.5 flex h-5 w-5 items-center justify-center rounded text-ink-3 hover:bg-raised hover:text-ink"
        >
          ×
        </button>
      </div>
      {near !== null && (
        <div className="mt-1 text-2xs text-ink-2">{near}</div>
      )}
      <div className="mt-0.5 font-mono text-2xs text-ink-3 tabular-nums">
        {peak.site.map((x) => x.toFixed(3)).join(" ")}
      </div>
      {/* Qn is a viewer-local ordinal (peaks.json is computed per node,
       * independently of the live session's diff_map_peaks table) - steer
       * users away from typing "Q7" into chat, where the agent's index
       * may point at a different peak. */}
      <div className="mt-1 text-2xs leading-snug text-ink-3">
        {t.peakOrdinalNote}
      </div>
      <button
        type="button"
        onClick={() => {
          draft.insert(peakQuote(peak, state.peaksNode));
          onClose();
        }}
        className="mt-2 h-6 w-full rounded-lg bg-accent/10 px-2 text-2xs font-medium text-accent transition-colors hover:bg-accent/15"
      >
        {t.peakQuote}
      </button>
    </div>
  );
}

// -------------------------------------------------------------- structure tab

function StructureTab({ compact = false }: { compact?: boolean }) {
  const { state, select, inspectInteraction, growStub, project, comparisonInfo, cameras, reflectionEvidenceAllowed, sceneReady: displayedSceneReady } = useCrystal();
  const cameraScope = state.comparison && comparisonInfo.data?.frame.status === "compatible"
    ? `pair:${state.comparison.node}:${state.comparison.baseline}` : `node:${state.viewNode}`;
  const cameraKey = JSON.stringify([project, cameraScope, state.mode, state.superN, state.packRadius, state.packCenter,
    state.packRange, state.growLevel, state.complete, state.growAll]);
  const renderedCameraKey = useRef(cameraKey);
  if (displayedSceneReady) renderedCameraKey.current = cameraKey;
  const structureOnly = state.nodes.find((node) => node.id === state.viewNode)?.structure_only === true;
  const draft = useComposerDraft();
  const [resetSignal, bumpReset] = useReducer((n: number) => n + 1, 0);
  const [exportSignal, bumpExport] = useReducer((n: number) => n + 1, 0);
  const [frameSignal, bumpFrame] = useReducer((n: number) => n + 1, 0);
  const [centerSignal, bumpCenter] = useReducer((n: number) => n + 1, 0);

  // Olex2-style click measurements: consecutive picks build a chain
  // (2=distance, 3=angle, 4=torsion); clicking a chained atom removes it.
  const [chain, setChain] = useState<number[]>([]);
  const [ixSel, setIxSel] = useState<InteractionRow | null>(null);
  useEffect(() => setIxSel(null), [state.scene]);
  const ov = state.overlays;
  const ixLayers = useMemo<Readonly<Record<InteractionKind, boolean>>>(
    () => ({
      hbond: ov.hbonds,
      pipi: ov.ixPipi,
      chpi: ov.ixChpi,
      chx: ov.ixChx,
      halogen: ov.ixHalogen,
      anion_pi: ov.ixAnionPi,
    }),
    [ov.hbonds, ov.ixPipi, ov.ixChpi, ov.ixChx, ov.ixHalogen, ov.ixAnionPi],
  );
  const [peakSel, setPeakSel] = useState<{
    peak: PeakEntry;
    index: number;
  } | null>(null);
  useEffect(() => {
    setChain([]);
    setPeakSel(null);
    // A repack can reorder atoms without changing their count.
  }, [state.scene]);

  const scene = state.scene;
  const readout = useMemo(() => {
    if (!scene || chain.length < 2) return null;
    const atoms = chain
      .map((i) => scene.atoms[i])
      .filter((a) => a !== undefined);
    if (atoms.length !== chain.length) return null;
    return measureReadout(
      atoms.map((a) => a.label),
      atoms.map((a) => a.xyz),
    );
  }, [scene, chain]);

  const anomalyIndices = useMemo(
    () => adpAnomalies(scene?.atoms ?? []).map((x) => x.index),
    [scene],
  );

  // 带图提问: the render goes to the composer as an attachment, with a
  // caption for everything the pixels cannot state (which node, how much
  // of the crystal, which layers are on). The image travels the same path
  // as a dragged file, so it inherits upload, thumbnail and retry.
  const handleFrame = (dataUrl: string) => {
    if (!displayedSceneReady) return;
    const bin = atob(dataUrl.slice(dataUrl.indexOf(",") + 1));
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    const stamp = new Date()
      .toTimeString()
      .slice(0, 8)
      .replaceAll(":", "");
    draft.attach([
      new File([bytes], t.crystal.paneFrameFile(state.scene?.node ?? "model", stamp), {
        type: "image/png",
      }),
    ]);
    draft.insert(
      frameQuote({
        node: state.scene?.node ?? null,
        spaceGroup: state.scene?.space_group,
        extent: extentLabel(state),
        nAtoms: state.scene?.meta.n_atoms,
        truncated: state.scene?.meta.truncated,
        layers: activeLayerLabels({ ...state.overlays,
          map: state.overlays.map && !structureOnly && reflectionEvidenceAllowed,
          peaks: state.overlays.peaks && !structureOnly && reflectionEvidenceAllowed }),
      }),
    );
  };

  // A fresh object literal here re-ran marching cubes over the whole-cell
  // void mask on EVERY render of this component - including the two the
  // 30 s node poll causes during a turn, and every click anywhere in the
  // pane. CrystalViewer's memo compares the two members structurally, so
  // this is belt-and-braces, but the object should be stable regardless.
  const voidsProp = useMemo(
    () =>
      state.overlays.voids &&
      state.voidsNode === state.viewNode &&
      state.voidsMeta !== null
        ? { buffer: state.voidBuffer, meta: state.voidsMeta }
        : null,
    [
      state.overlays.voids,
      state.voidsNode,
      state.viewNode,
      state.voidsMeta,
      state.voidBuffer,
    ],
  );

  // 简化网 overlay (round-2 R4): the node-linker net lives in the node's
  // analysis product (the same file the 分析 tab shows), fetched the first
  // time the pill is on for a node and kept per node - a node is immutable,
  // so is its product. The pill's own status pill says when it is loading.
  type NetProp = { nodes: NetNode[]; edges: NetEdge[] };
  const netCache = useRef(new Map<string, NetProp>());
  const [netData, setNetData] = useState<{ node: string; net: NetProp } | null>(null);
  const [netStatus, setNetStatus] = useState<"idle" | "loading" | "error">("idle");
  useEffect(() => {
    if (!state.overlays.net || !project || !state.viewNode) return undefined;
    const node = state.viewNode;
    const hit = netCache.current.get(node);
    if (hit) {
      setNetData({ node, net: hit });
      return undefined;
    }
    const ctrl = new AbortController();
    setNetStatus("loading");
    getRefineTopology(project, node, ctrl.signal)
      .then((topology) => {
        if (ctrl.signal.aborted) return;
        const sn = topology?.simplified_net;
        const net: NetProp = sn ? { nodes: sn.nodes, edges: sn.edges } : { nodes: [], edges: [] };
        netCache.current.set(node, net);
        setNetData({ node, net });
        setNetStatus("idle");
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setNetStatus("error");
      });
    return () => ctrl.abort();
  }, [state.overlays.net, project, state.viewNode]);
  const netProp = useMemo(
    () =>
      state.overlays.net && netData !== null && netData.node === state.viewNode
        ? netData.net
        : null,
    [state.overlays.net, netData, state.viewNode],
  );

  // Which cells the per-cell overlays are instanced over (round-2 R2.2,
  // defect D7). Derived from the SAME scene object the viewer gets, so the
  // two can never describe different slices; a scene cached before the
  // contract has no range and keeps the old origin-cell behaviour.
  const tilesProp = useMemo(
    () => state.scene?.range?.tiles ?? ORIGIN_TILES,
    [state.scene],
  );
  const layerCoverage = useMemo(() => {
    const requestedTiles = state.scene?.range?.n_tiles ?? tilesProp.length;
    const positivePeaks = state.peaksNode === state.viewNode
      ? state.peaks?.filter((peak) => peak.height > 0).length ?? 0
      : 0;
    return overlayCoverage(requestedTiles, tilesProp.length, positivePeaks);
  }, [state.scene, state.peaks, state.peaksNode, state.viewNode, tilesProp]);
  const layerLimitLabels: string[] = [];
  if (
    state.overlays.symm
    && (state.scene?.sym_elements?.length ?? 0) > 0
    && layerCoverage.symmetry.drawnTiles < layerCoverage.symmetry.requestedTiles
  ) {
    layerLimitLabels.push(
      t.crystal.paneSymmetryCoverage(layerCoverage.symmetry.drawnTiles, layerCoverage.symmetry.requestedTiles),
    );
  }
  if (
    state.overlays.peaks
    && layerCoverage.peaks.requestedSpheres > 0
    && layerCoverage.peaks.drawnSpheres < layerCoverage.peaks.requestedSpheres
  ) {
    layerLimitLabels.push(
      t.crystal.panePeaksCoverage(layerCoverage.peaks.drawnSpheres, layerCoverage.peaks.requestedSpheres),
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* The crystal owns the pane (round-2 R1.2, defect D4): the canvas is
       * the only flex child and every control floats on top of it
       * (CrystalToolbar). The old layout gave a 45%-tall control block the
       * first claim on height and the 3D view whatever was left. */}
      <div data-testid="structure-viewport" className={cx("relative m-2 min-w-0 flex-1 overflow-hidden rounded-card border border-line bg-surface [container-type:size]",
        compact ? "min-h-0" : "min-h-[12rem]")}>
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center gap-2 text-xs text-ink-3">
              <Spinner />
              {t.loading}
            </div>
          }
        >
          <CrystalViewer
            scene={state.scene}
            cameraKey={renderedCameraKey.current}
            cameras={cameras}
            interactive={displayedSceneReady}
            mapBuffer={
              state.mapNode === state.viewNode ? state.mapBuffer : null
            }
            showMap={state.overlays.map && !structureOnly && reflectionEvidenceAllowed}
            mapKind={state.mapKind}
            iso={state.iso}
            showPolyhedra={state.overlays.polyhedra}
            hiddenElems={state.hiddenElems}
            spin={state.overlays.spin}
            drawStyle={state.drawStyle}
            showLabels={state.overlays.labels}
            showHbonds={state.overlays.hbonds}
            showStubs={state.overlays.stubs}
            partFilter={state.partFilter}
            colorByPart={state.overlays.parts}
            pubStyle={state.overlays.pub}
            exportSignal={exportSignal}
            frameSignal={frameSignal}
            onFrame={handleFrame}
            onGrowStub={(stub) => growStub(stub.i, stub.op)}
            measureChain={chain}
            onSelectAtom={(atom, index) => {
              if (state.sceneNode !== state.viewNode || state.sceneStatus !== "ok") return;
              select({ atom, index });
              setIxSel(null);
              setChain((prev) => {
                if (prev.includes(index)) {
                  return prev.filter((i) => i !== index);
                }
                const next = [...prev, index];
                return next.length > 4 ? next.slice(next.length - 4) : next;
              });
            }}
            resetSignal={resetSignal}
            centerSignal={centerSignal + state.focusRequest}
            centerIndex={state.sceneNode === state.viewNode ? state.selection?.index ?? null : null}
            highlightIndex={state.sceneNode === state.viewNode ? state.selection?.index ?? null : null}
            anomalyIndices={anomalyIndices}
            peaks={
              state.overlays.peaks && reflectionEvidenceAllowed && state.peaksNode === state.viewNode
                ? state.peaks
                : null
            }
            onSelectPeak={(peak, index) => setPeakSel({ peak, index })}
            ixLayers={ixLayers}
            onSelectInteraction={(row) => {
              setIxSel(row);
              setPeakSel(null);
              if (scene?.node) inspectInteraction(scene.node, row, row);
            }}
            voids={voidsProp}
            net={netProp}
            tiles={tilesProp}
            slab={state.slab}
            viewDepth={state.viewDepth}
            showSymm={state.overlays.symm}
          />
        </Suspense>
        {state.comparison && !displayedSceneReady && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface text-sm text-ink-3" role="status">
            {state.sceneStatus === "error" ? t.crystal.cannotLoadNode(state.viewNode) : t.crystal.loadingNode(state.viewNode)}
          </div>
        )}
        {state.sceneStatus === "loading" && (
          <div className="absolute top-2.5 right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            <Spinner className="h-3 w-3" />
            {t.sceneLoading}
          </div>
        )}
        {state.overlays.map && reflectionEvidenceAllowed && state.mapStatus === "loading" && (
          <div className="absolute top-9 right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            <Spinner className="h-3 w-3" />
            {t.mapLoading}
          </div>
        )}
        {state.overlays.peaks && reflectionEvidenceAllowed && state.peaksStatus === "loading" && (
          <div className="absolute top-[3.9rem] right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            <Spinner className="h-3 w-3" />
            {t.peaksLoading}
          </div>
        )}
        {state.overlays.net && netStatus === "loading" && (
          <div className="absolute top-[7.1rem] right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            <Spinner className="h-3 w-3" />
            {t.netLoading}
          </div>
        )}
        {state.overlays.net && netStatus === "error" && (
          <div className="absolute top-[7.1rem] right-2.5 z-10 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-danger backdrop-blur-sm">
            {t.anTopologyFailed}
          </div>
        )}
        {state.overlays.net && netProp !== null && netProp.nodes.length === 0 && (
          <div className="absolute top-[7.1rem] right-2.5 z-10 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            {t.netEmpty}
          </div>
        )}
        {state.overlays.voids && state.voidsStatus === "loading" && (
          <div className="absolute top-[5.5rem] right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
            <Spinner className="h-3 w-3" />
            {t.voidsLoading}
          </div>
        )}
        {state.overlays.voids &&
          state.voidsStatus === "ok" &&
          state.voidsNode === state.viewNode &&
          state.voidsMeta !== null &&
          (state.voidsMeta.n_voids === 0 ? (
            <div className="absolute top-[5.5rem] right-2.5 z-10 rounded-pill bg-bg/85 px-2.5 py-1 text-2xs text-ink-3 backdrop-blur-sm">
              {t.voidsNone}
            </div>
          ) : (
            /* the pore total is the number a solvent-mask / SQUEEZE
             * decision actually turns on, and it was previously visible
             * only as an isosurface you had to eyeball */
            <div className="absolute top-[5.5rem] right-2.5 z-10 flex items-center gap-1.5 rounded-pill bg-bg/85 py-1 pr-1 pl-2.5 text-2xs text-ink-2 backdrop-blur-sm">
              <span className="font-mono tabular-nums">
                {t.crystal.paneVoidsPerCell(state.voidsMeta.n_voids)} ·{" "}
                {typeof state.voidsMeta.solvent_volume_A3 === "number"
                  ? Math.round(state.voidsMeta.solvent_volume_A3) : "—"} Å³
                {typeof state.voidsMeta.total_solvent_electrons_per_cell === "number"
                  ? ` · ${Math.round(state.voidsMeta.total_solvent_electrons_per_cell)} e`
                  : ` · ${t.electronsNotComputed}`}
              </span>
              <button
                type="button"
                title={t.voidsQuoteTip}
                onClick={() =>
                  draft.insert(
                    voidQuote(
                      state.voidsMeta?.solvent_volume_A3 ?? null,
                      state.voidsMeta?.total_solvent_electrons_per_cell ?? null,
                      state.voidsNode,
                    ),
                  )
                }
                className="h-4.5 rounded-pill px-1.5 text-2xs font-medium text-accent transition-colors hover:bg-accent/10"
              >
                {t.measureQuote}
              </button>
            </div>
          ))}
        {/* the atom cap is not a detail once 生长/超胞 can be pushed: what
         * you are looking at is then a PIECE of the structure, and reading
         * "56 原子" as the whole thing is a real misreading. This used to
         * be the word 已截断 in a 10 px corner string. */}
        <div className="absolute top-2 left-2 z-10 flex flex-wrap items-center gap-1.5">
          <ExtentMenu onAssemble={() => draft.insert(t.assembleTemplate)} />
          {state.scene?.meta.truncated === true && state.sceneStatus !== "loading" && (
            <span
              className="rounded-pill border border-warn/40 bg-warn/10 px-2.5 py-1 text-2xs text-warn backdrop-blur-sm"
              title={t.sceneTruncatedTip}
            >
              {t.sceneTruncated}
            </span>
          )}
          {/* A SEPARATE pill from 显示已截断 on purpose (round-2 R2.2): the
           * atoms may all be drawn while the per-cell layers cover only the
           * centre-most cells. Merging the two would tell one lie about two
           * different situations. */}
          {/* grow-all (Olex2 `grow`) stopped at a lattice repeat or at the
           * atom budget: a periodic net drawn over one period is not "the
           * whole molecule", and the pill says which of the two it was. */}
          {state.scene?.grow_all &&
            state.sceneStatus !== "loading" &&
            (state.scene.grow_all.budget_hit || state.scene.grow_all.periodic_edges > 0) && (
              <span
                className="rounded-pill border border-warn/40 bg-warn/10 px-2.5 py-1 text-2xs text-warn backdrop-blur-sm"
                title={t.growAllTip}
              >
                {state.scene.grow_all.budget_hit ? t.growAllBudget : t.growAllPeriodic}
              </span>
            )}
          {state.scene?.range?.tiles_truncated === true &&
            state.sceneStatus !== "loading" && (
              <span
                className="rounded-pill border border-warn/40 bg-warn/10 px-2.5 py-1 text-2xs text-warn backdrop-blur-sm"
                title={t.layerRangeTruncatedTip}
              >
                {t.layerRangeTruncated(
                  state.scene.range.tiles.length,
                  state.scene.range.n_tiles,
                )}
              </span>
            )}
          {layerLimitLabels.length > 0 && state.sceneStatus !== "loading" && (
            <span
              className="rounded-pill border border-warn/40 bg-warn/10 px-2.5 py-1 text-2xs text-warn backdrop-blur-sm"
              title={t.crystal.paneLayerLimitTip}
            >
              {layerLimitLabels.join(" · ")}
            </span>
          )}
        </div>
        {state.sceneStatus === "error" && (
          <div className="absolute inset-x-2.5 top-11 z-10">
            <AlertBanner>
              {t.sceneError}
              {state.sceneError ? `${t.colon}${state.sceneError}` : ""}
            </AlertBanner>
          </div>
        )}
        {readout !== null && (
          <div className="absolute top-11 left-2 z-10 flex items-center gap-2 rounded-pill border border-line bg-bg/90 py-1 pr-1.5 pl-2.5 shadow-sm backdrop-blur-sm">
            <span className="font-mono text-2xs text-ink tabular-nums">
              {readout.text}
            </span>
            <button
              type="button"
              title={t.measureQuoteTip}
              onClick={() => {
                draft.insert(measureQuote(
                  readout.text,
                  scene?.node,
                  chain.flatMap((i) => scene?.atoms[i] ? [scene.atoms[i]] : []),
                ));
                setChain([]);
              }}
              className="h-4.5 rounded-pill px-1.5 text-2xs font-medium text-accent transition-colors hover:bg-accent/10"
            >
              {t.measureQuote}
            </button>
            <button
              type="button"
              aria-label={t.measureClear}
              title={t.measureClear}
              onClick={() => setChain([])}
              className="flex h-4.5 w-4.5 items-center justify-center rounded-pill text-ink-3 hover:bg-raised hover:text-ink"
            >
              ×
            </button>
          </div>
        )}
        {!compact && <SelectionCard onCenter={bumpCenter} />}
        {displayedSceneReady && reflectionEvidenceAllowed && peakSel !== null && (
          <PeakCard sel={peakSel} onClose={() => setPeakSel(null)} />
        )}
        {!compact && displayedSceneReady && ixSel !== null && state.scene?.interactions !== undefined && (
          <InteractionCard
            row={ixSel}
            meta={state.scene.interactions}
            onClose={() => setIxSel(null)}
          />
        )}
        <FloatingBar onResetView={bumpReset} onExport={bumpExport} onAskWithView={bumpFrame} />
        {/* the scene's counts used to be captioned here; they moved to the
         * header card's status line. Bottom-right is where the cell-axis
         * triad lands, and in a short viewport the two drew through each
         * other - text over the model is exactly the kind of clutter the
         * viewport should not have. */}
      </div>
    </div>
  );
}

function AnalysisWorkspace() {
  const [pinned, toggle] = useSection("an.keep-structure", true);
  const [proportion, setProportion] = useState(() => {
    try {
      const value = Number(localStorage.getItem("cp.analysis.structure-share"));
      return value >= 30 && value <= 70 ? value : 55;
    } catch { return 55; }
  });
  const resize = (value: number) => {
    setProportion(value);
    try { localStorage.setItem("cp.analysis.structure-share", String(value)); } catch { /* session-only preference */ }
  };
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="analysis-workspace">
      {pinned && <div style={{ flexBasis: `${proportion}%` }} className="flex min-h-0 shrink-0 flex-col"><StructureTab compact /></div>}
      <div className="flex shrink-0 items-center gap-3 border-y border-line px-3 py-1">
        <button type="button" aria-expanded={pinned} onClick={toggle} title={t.analysisKeepStructure}
          className="shrink-0 rounded py-1 text-xs text-ink-2 hover:text-ink">
          {pinned ? t.crystal.paneCollapseStructure : t.crystal.paneShowStructure}
        </button>
        {pinned && <input type="range" min={30} max={70} step={5} value={proportion}
          aria-label={t.crystal.paneStructureShareAria} aria-valuetext={t.crystal.paneStructureShareValue(proportion)}
          onChange={(e) => resize(Number(e.target.value))}
          className="h-1 min-w-0 flex-1 accent-(--color-accent)" />}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden"><AnalysisPanel /></div>
    </div>
  );
}

function StructureOnlyNotice({ node }: { node?: RefineNode }) {
  if (!node?.structure_only) return null;
  const reported = node.reported_reference?.values;
  return (
    <div className="shrink-0 border-b border-line bg-surface/60 px-3 py-2 text-xs text-ink-2" data-testid="structure-only-notice">
      <div className="font-medium">{t.structureOnlyTitle}</div>
      <div className="mt-0.5 text-2xs text-ink-3">{t.structureOnlyNote}</div>
      {reported && ["r1", "wr2", "goof"].some((key) => reported[key] != null) && (
        <details className="mt-1 text-2xs text-ink-3">
          <summary className="cursor-pointer">{t.structureReportedMetrics}</summary>
          <div className="mt-1 font-mono">{[["r1", "R1"], ["wr2", "wR2"], ["goof", "GooF"]]
            .filter(([key]) => reported[key] != null).map(([key, label]) => `${label} ${reported[key]}`).join(" · ")}</div>
        </details>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- pane

export function CrystalPane({ tab }: { tab: CrystalTabId }) {
  const { state, refreshNodes } = useCrystal();
  const viewed = state.nodes.find((node) => node.id === (state.viewNode ?? state.activeNode));

  // checkCIF results live on the thread, not the node store - the 验证 tab
  // must render even for a project with no refinement nodes yet
  if (tab === "validation") {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <StructureOnlyNotice node={viewed} />
        <ValidationPanel />
      </div>
    );
  }

  if (state.nodesStatus === "loading" && state.nodes.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-xs text-ink-3">
        <Spinner />
        {t.nodesLoading}
      </div>
    );
  }
  if (state.nodes.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <div className="text-sm text-ink-3">{t.nodesEmpty}</div>
        <button
          type="button"
          onClick={refreshNodes}
          className="h-7 rounded-lg border border-line px-3 text-xs text-ink-2 transition-colors hover:bg-raised"
        >
          {t.refreshNodes}
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <HistoryBanner />
      <StructureOnlyNotice node={viewed} />
      {state.comparison ? <StructureComparison /> : <StructureHeader />}
      {tab === "structure" && <StructureTab />}
      {tab === "analysis" && <AnalysisWorkspace />}
      {tab === "nodes" && <NodeTreePanel />}
      {tab === "metrics" && <MetricsPanel />}
      {tab === "artifacts" && <ArtifactsPanel />}
    </div>
  );
}

/** Lineage of `id` (oldest → … → id) following parent links. */
export function lineageOf(nodes: RefineNode[], id: string | null): RefineNode[] {
  if (id === null) return [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: RefineNode[] = [];
  let cur = byId.get(id) ?? null;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    out.push(cur);
    cur = cur.parent !== null ? (byId.get(cur.parent) ?? null) : null;
  }
  return out.reverse();
}
