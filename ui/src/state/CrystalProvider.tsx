/** Crystal-pane state provider (P2).
 *
 * Data flows:
 * - nodes: fetched on mount and again whenever the thread reducer raises a
 *   crystalSignal (a crystal-mutating tool completed ok);
 * - scene: fetched on (viewNode, mode, overlays.diff) with latest-wins
 *   AbortController semantics (polyhedra are always requested; showing them
 *   is a client-side toggle so it costs nothing);
 * - map: Fo−Fc CCP4 buffer fetched lazily when the overlay is on, cached
 *   per node (small LRU - buffers are ~4 MB).
 *
 * Mounted at the workbench-shell level (inside MaybeThreadProvider) so the
 * pane keeps its mode/overlays/pinned node across pane collapse and route
 * changes within a project.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import {
  getRefineMap,
  getRefineNodes,
  getRefinePeaks,
  getRefineScene,
  getRefineData,
  getRefineVoidMap,
  getRefineVoids,
  type MapKind,
} from "../lib/wbApi";
import type {
  DataBlockResponse,
  PeakEntry,
  UniqueInteractionRow,
  InteractionRow,
  VoidsResponse,
} from "../lib/wbTypes";
import {
  crystalReducer,
  initialCrystalState,
  sceneMatchesRequest,
  type CrystalMode,
  type CrystalOverlays,
  type CrystalSelection,
  type CrystalState,
  type DrawStyle,
  type GrowLevel,
  type SlabState,
  type SuperN,
  type PackRange,
  type ViewDepthState,
} from "./crystalReducer";
import { useThreadOptional } from "./ThreadProvider";
import { ComparisonCameras } from "../lib/structureComparison";
import { useNodeComparison, type NodeComparisonResult } from "./useNodeComparison";

const MAP_CACHE_MAX = 6;

export interface CrystalContextValue {
  state: CrystalState;
  project: string | null;
  comparisonInfo: NodeComparisonResult;
  sceneReady: boolean;
  cameras: ComparisonCameras;
  reflectionEvidenceAllowed: boolean;
  beginComparison: (baseline?: string | null) => void;
  comparisonSide: (node: string) => void;
  endComparison: () => void;
  viewNode: (node: string) => void;
  followLatest: () => void;
  setMode: (mode: CrystalMode) => void;
  /** ball-and-stick / wireframe / ORTEP / spacefill (Olex2 representations) */
  setDrawStyle: (style: DrawStyle) => void;
  /** shells of symmetry completion accumulated on top of the current
   * slice; 0 = ungrown (Olex2 fuse) */
  setGrowLevel: (level: GrowLevel) => void;
  /** show/hide every atom of one element (Olex2's element row) */
  toggleElem: (elem: string) => void;
  /** supercell edge; also switches into 超胞 */
  setSuperN: (n: SuperN) => void;
  /** Olex2 pack r: whole molecules within `radius` Å of an ASU atom
   * (null = the ASU centroid); also switches into 半径 */
  setPackRadius: (radius: number, center: string | null) => void;
  /** Olex2 pack a1 a2 b1 b2 c1 c2; also switches into 范围 */
  setPackRange: (range: PackRange) => void;
  /** Olex2 grow -w */
  setComplete: (complete: boolean) => void;
  setGrowAll: (growAll: boolean) => void;
  toggleOverlay: (overlay: keyof CrystalOverlays) => void;
  setIso: (iso: number) => void;
  /** switch the density overlay between Fo−Fc and 2Fo−Fc */
  setMapKind: (kind: MapKind) => void;
  select: (selection: CrystalSelection | null) => void;
  /** Select an exact current-scene instance and ask the viewer to center it. */
  locate: (node: string, selection: CrystalSelection) => void;
  /** Link a canonical analysis row to its exact rendered instance. */
  inspectInteraction: (node: string, row: UniqueInteractionRow, instance?: InteractionRow) => void;
  clearInspection: () => void;
  /** round-3 R6: view `node` (history, no checkout) and select the atom a
   * transcript anchor names once that node's scene is on screen */
  selectLabel: (node: string, label: string) => void;
  refreshNodes: () => void;
  /** materialize a clicked grow stub (Olex2 mode-grow) */
  growStub: (i: number, op: string) => void;
  /** clear all user-grown instances (Olex2 fuse) */
  fuse: () => void;
  setPartFilter: (part: number | null) => void;
  /** pin a diff baseline node (any-vs-any compare); null = parent */
  setDiffVs: (node: string | null) => void;
  /** periodic slab clip for pore cross-sections (null = off) */
  setSlab: (slab: SlabState | null) => void;
  /** camera-space fog/clip, independent of the scientific section slab */
  setViewDepth: (viewDepth: Partial<ViewDepthState>) => void;
  resetViewDepth: () => void;
}

const CrystalContext = createContext<CrystalContextValue | null>(null);

export function useCrystal(): CrystalContextValue {
  const ctx = useContext(CrystalContext);
  if (ctx === null) {
    throw new Error("useCrystal must be used inside CrystalProvider");
  }
  return ctx;
}

/** null outside the provider (chat rows render in tests without a pane). */
export function useCrystalOptional(): CrystalContextValue | null {
  return useContext(CrystalContext);
}

function sceneParams(
  mode: CrystalMode,
  diff: boolean,
  grown: { i: number; op: string }[],
  diffVs: string | null,
  contacts: boolean,
  growLevel: GrowLevel,
  superN: SuperN,
  packRadius: number,
  packCenter: string | null,
  packRange: PackRange,
  complete: boolean,
  interactions: boolean,
  growAll: boolean,
): {
  mode: string;
  interactions?: 0 | 1;
  n?: number;
  hops?: number;
  polyhedra: 0 | 1;
  diff: 0 | 1;
  vs?: string;
  extra?: string;
  contacts?: 0 | 1;
  complete?: 0 | 1;
  grow_all?: 0 | 1;
  radius?: number;
  center?: string;
  lo?: string;
  hi?: string;
} {
  const base = {
    polyhedra: 1 as const,
    diff: diff ? (1 as const) : (0 as const),
    ...(diff && diffVs !== null ? { vs: diffVs } : {}),
    ...(grown.length > 0 ? { extra: JSON.stringify(grown) } : {}),
    ...(contacts ? { contacts: 1 as const } : {}),
    ...(complete ? { complete: 1 as const } : {}),
    ...(growAll ? { grow_all: 1 as const } : {}),
    ...(interactions ? { interactions: 1 as const } : {}),
  };
  // hops rides along with EVERY slice: growing is an action applied to
  // what is on screen, not a slice of its own (Olex2 `pack` then `grow`)
  const grow = growLevel > 0 ? { hops: growLevel } : {};
  switch (mode) {
    case "asu":
      return { mode: "asu", ...grow, ...base };
    case "cell":
      return { mode: "cell", ...grow, ...base };
    case "super":
      return { mode: "supercell", n: superN, ...grow, ...base };
    case "radius":
      return {
        mode: "radius",
        radius: packRadius,
        ...(packCenter ? { center: packCenter } : {}),
        ...grow,
        ...base,
      };
    case "range":
      return {
        mode: "range",
        lo: packRange.lo.join(","),
        hi: packRange.hi.join(","),
        ...grow,
        ...base,
      };
  }
}

export function CrystalProvider({
  project,
  children,
}: {
  project: string | null;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(
    crystalReducer,
    undefined,
    initialCrystalState,
  );
  const thread = useThreadOptional();
  const signalSeq = thread?.state.crystalSignal?.seq ?? 0;
  const [refreshTick, bumpRefresh] = useReducer((n: number) => n + 1, 0);
  const turnActive = thread?.state.turn.active === true;
  const cameras = useRef(new ComparisonCameras()).current;
  const comparedNode = state.nodes.find((node) => node.id === (state.comparison?.node ?? state.viewNode));
  const comparedBaseline = state.nodes.find((node) => node.id === (state.comparison?.baseline ?? state.diffVs ?? comparedNode?.parent));
  const comparisonInfo = useNodeComparison(project, comparedNode, comparedBaseline);
  const sideSource = state.viewNode === comparisonInfo.data?.node
    ? comparisonInfo.data.sources.node : state.viewNode === comparisonInfo.data?.baseline
      ? comparisonInfo.data.sources.baseline : null;
  const reflectionEvidenceAllowed = state.comparison === null
    || sideSource?.evidence?.reflection_recompute === true;
  const comparisonOrigin = useRef<{ tab: string; baseline: string | null }>({ tab: "structure", baseline: null });
  const beginComparison = useCallback((baseline: string | null = null) => {
    if (!state.comparison) comparisonOrigin.current = {
      tab: new URLSearchParams(window.location.search).get("tab") ?? "structure", baseline,
    };
    dispatch({ type: "begin_comparison", baseline });
    window.dispatchEvent(new CustomEvent("cp:right-tab", { detail: "structure" }));
  }, [state.comparison]);
  const comparisonSide = useCallback((node: string) => dispatch({ type: "comparison_side", node }), []);
  const endComparison = useCallback(() => {
    dispatch({ type: "end_comparison" });
    const origin = comparisonOrigin.current;
    window.dispatchEvent(new CustomEvent("cp:right-tab", { detail: origin.tab }));
    requestAnimationFrame(() => {
      const target = origin.baseline ? document.querySelector<HTMLButtonElement>(`[data-comparison-node="${CSS.escape(origin.baseline)}"]`)
        : document.querySelector<HTMLButtonElement>('[data-comparison-entry="parent"]');
      (target ?? document.querySelector<HTMLButtonElement>('aside [aria-label="结构工作区页面"] button'))?.focus();
    });
  }, []);

  // long-turn liveness: mutations outside the MCP event stream (direct
  // invoke shims / shell stages) emit no crystal signal - poll gently
  // while a turn runs so the node tree tracks a 50-node session instead
  // of freezing on n0000 until the end
  useEffect(() => {
    if (!project || !turnActive) return undefined;
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") bumpRefresh();
    }, 30_000);
    return () => window.clearInterval(t);
  }, [project, turnActive]);

  // ------------------------------------------------------------- nodes fetch
  useEffect(() => {
    if (!project) return undefined;
    let cancelled = false;
    dispatch({ type: "nodes_loading" });
    void getRefineNodes(project)
      .then((res) => {
        if (cancelled) return;
        dispatch({
          type: "nodes_ok",
          nodes: res.nodes,
          deliveries: res.deliveries ?? [],
          activeNode: res.active_node,
          activeBranch: res.active_branch,
          branches: res.branches,
        });
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: "nodes_error" });
      });
    return () => {
      cancelled = true;
    };
  }, [project, signalSeq, refreshTick]);

  // ------------------------------------------------------------- scene fetch
  const { viewNode: viewedId, mode, grown, diffVs, growLevel, superN } =
    state;
  const { packRadius, packCenter, packRange, complete, growAll } = state;
  const diff = state.overlays.diff && !state.comparison && comparisonInfo.data?.frame.status === "compatible";
  const contactsOn = state.overlays.contacts;
  const ov = state.overlays;
  const ixOn = ov.hbonds || ov.ixPipi || ov.ixChpi || ov.ixChx
    || ov.ixHalogen || ov.ixAnionPi;
  const params = useMemo(() => sceneParams(mode, diff, grown, diffVs, contactsOn, growLevel, superN,
    packRadius, packCenter, packRange, complete, ixOn, growAll),
  [mode, diff, grown, diffVs, contactsOn, growLevel, superN, packRadius, packCenter, packRange, complete, ixOn, growAll]);
  const key = JSON.stringify([project, viewedId, params]);
  const sceneReady = sceneMatchesRequest(state, key);
  useEffect(() => {
    if (!project || !viewedId) return undefined;
    const ctrl = new AbortController();
    dispatch({ type: "scene_loading", key });
    void getRefineScene(project, viewedId, params, ctrl.signal)
      .then((scene) => {
        if (!ctrl.signal.aborted) dispatch({ type: "scene_ok", scene, key });
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        dispatch({
          type: "scene_error", key,
          error: e instanceof Error ? e.message : String(e),
        });
      });
    return () => ctrl.abort();
  }, [project, viewedId, params, key]);

  // --------------------------------------------------------------- map fetch
  const structureOnly = state.nodes.find((node) => node.id === viewedId)?.structure_only === true;
  const mapOn = state.overlays.map && !structureOnly && reflectionEvidenceAllowed;
  const mapKind = state.mapKind;
  const mapCache = useRef(new Map<string, ArrayBuffer>());
  useEffect(() => {
    if (!project || !viewedId || !mapOn) return undefined;
    const key = `${viewedId}|${mapKind}`;
    const cached = mapCache.current.get(key);
    if (cached) {
      dispatch({ type: "map_ok", node: viewedId, buffer: cached });
      return undefined;
    }
    const ctrl = new AbortController();
    dispatch({ type: "map_loading" });
    void getRefineMap(project, viewedId, mapKind, ctrl.signal)
      .then((buffer) => {
        if (ctrl.signal.aborted) return;
        const cache = mapCache.current;
        cache.set(key, buffer);
        while (cache.size > MAP_CACHE_MAX) {
          const oldest = cache.keys().next().value;
          if (oldest === undefined) break;
          cache.delete(oldest);
        }
        dispatch({ type: "map_ok", node: viewedId, buffer });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) dispatch({ type: "map_error" });
      });
    return () => ctrl.abort();
  }, [project, viewedId, mapOn, mapKind]);

  // ------------------------------------------------------------- peaks fetch
  const peaksOn = state.overlays.peaks && !structureOnly && reflectionEvidenceAllowed;
  const peaksCache = useRef(new Map<string, PeakEntry[]>());
  useEffect(() => {
    if (!project || !viewedId || !peaksOn) return undefined;
    const cached = peaksCache.current.get(viewedId);
    if (cached) {
      dispatch({ type: "peaks_ok", node: viewedId, peaks: cached });
      return undefined;
    }
    const ctrl = new AbortController();
    dispatch({ type: "peaks_loading" });
    void getRefinePeaks(project, viewedId, ctrl.signal)
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        const cache = peaksCache.current;
        cache.set(viewedId, resp.peaks);
        while (cache.size > MAP_CACHE_MAX) {
          const oldest = cache.keys().next().value;
          if (oldest === undefined) break;
          cache.delete(oldest);
        }
        dispatch({ type: "peaks_ok", node: viewedId, peaks: resp.peaks });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) dispatch({ type: "peaks_error" });
      });
    return () => ctrl.abort();
  }, [project, viewedId, peaksOn]);

  // ------------------------------------------------------------- voids fetch
  const voidsOn = state.overlays.voids;
  const voidsCache = useRef(
    new Map<string, { meta: VoidsResponse; buffer: ArrayBuffer | null }>(),
  );
  useEffect(() => {
    if (!project || !viewedId || !voidsOn) return undefined;
    const cached = voidsCache.current.get(viewedId);
    if (cached) {
      dispatch({
        type: "voids_ok",
        node: viewedId,
        meta: cached.meta,
        buffer: cached.buffer,
      });
      return undefined;
    }
    const ctrl = new AbortController();
    dispatch({ type: "voids_loading" });
    void (async () => {
      const meta = await getRefineVoids(project, viewedId, ctrl.signal);
      const buffer = meta.map
        ? await getRefineVoidMap(project, viewedId, ctrl.signal)
        : null;
      return { meta, buffer };
    })()
      .then(({ meta, buffer }) => {
        if (ctrl.signal.aborted) return;
        const cache = voidsCache.current;
        cache.set(viewedId, { meta, buffer });
        while (cache.size > MAP_CACHE_MAX) {
          const oldest = cache.keys().next().value;
          if (oldest === undefined) break;
          cache.delete(oldest);
        }
        dispatch({ type: "voids_ok", node: viewedId, meta, buffer });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) dispatch({ type: "voids_error" });
      });
    return () => ctrl.abort();
  }, [project, viewedId, voidsOn]);

  // -------------------------------------------------------- data block fetch
  // Nodes committed before `data` existed carry null, and the header card
  // then had no Rint, no d_min, no completeness - the three numbers that
  // say what R1 was ever going to be able to reach. They are recoverable
  // by merging the reflection file, which is far too expensive to do for
  // 70 nodes on every poll, so it happens for the one node on screen and
  // only when that node has nothing of its own.
  const dataCache = useRef(new Map<string, DataBlockResponse>());
  const viewedHasData =
    state.nodes.find((n) => n.id === viewedId)?.data != null;
  useEffect(() => {
    if (!project || !viewedId || viewedHasData || structureOnly || state.comparison) return undefined;
    const cached = dataCache.current.get(viewedId);
    if (cached) {
      dispatch({ type: "data_block_ok", node: viewedId, block: cached });
      return undefined;
    }
    const ctrl = new AbortController();
    getRefineData(project, viewedId, ctrl.signal)
      .then((block) => {
        if (ctrl.signal.aborted) return;
        const cache = dataCache.current;
        cache.set(viewedId, block);
        while (cache.size > MAP_CACHE_MAX) {
          const oldest = cache.keys().next().value;
          if (oldest === undefined) break;
          cache.delete(oldest);
        }
        dispatch({ type: "data_block_ok", node: viewedId, block });
      })
      .catch(() => {
        /* a missing data block is the status quo ante, not an error the
         * user needs to see - the card just omits those tiles */
      });
    return () => ctrl.abort();
  }, [project, viewedId, viewedHasData, structureOnly, state.comparison]);

  // ----------------------------------------------------------------- actions
  const viewNode = useCallback(
    (node: string) => dispatch({ type: "view_node", node }),
    [],
  );
  const followLatest = useCallback(
    () => dispatch({ type: "follow_latest" }),
    [],
  );
  const setMode = useCallback(
    (m: CrystalMode) => dispatch({ type: "set_mode", mode: m }),
    [],
  );
  const setDrawStyle = useCallback(
    (style: DrawStyle) => dispatch({ type: "set_draw_style", style }),
    [],
  );
  const setGrowLevel = useCallback(
    (level: GrowLevel) => dispatch({ type: "set_grow_level", level }),
    [],
  );
  const toggleElem = useCallback(
    (elem: string) => dispatch({ type: "toggle_elem", elem }),
    [],
  );
  const setSuperN = useCallback(
    (n: SuperN) => dispatch({ type: "set_super_n", n }),
    [],
  );
  const setPackRadius = useCallback(
    (radius: number, center: string | null) =>
      dispatch({ type: "set_pack_radius", radius, center }),
    [],
  );
  const setPackRange = useCallback(
    (range: PackRange) => dispatch({ type: "set_pack_range", range }),
    [],
  );
  const setComplete = useCallback(
    (complete: boolean) => dispatch({ type: "set_complete", complete }),
    [],
  );
  const setGrowAll = useCallback(
    (growAll: boolean) => dispatch({ type: "set_grow_all", growAll }),
    [],
  );
  const toggleOverlay = useCallback(
    (overlay: keyof CrystalOverlays) =>
      dispatch({ type: "toggle_overlay", overlay }),
    [],
  );
  const setIso = useCallback(
    (iso: number) => dispatch({ type: "set_iso", iso }),
    [],
  );
  const setMapKind = useCallback(
    (kind: MapKind) => dispatch({ type: "set_map_kind", kind }),
    [],
  );
  const select = useCallback(
    (selection: CrystalSelection | null) =>
      dispatch({ type: "select", selection }),
    [],
  );
  const locate = useCallback(
    (node: string, selection: CrystalSelection) => dispatch({ type: "locate", node, selection }),
    [],
  );
  const inspectInteraction = useCallback(
    (node: string, row: UniqueInteractionRow, instance?: InteractionRow) =>
      dispatch({ type: "inspect_interaction", node, row, instance }),
    [],
  );
  const clearInspection = useCallback(
    () => dispatch({ type: "clear_inspection" }),
    [],
  );
  const selectLabel = useCallback((node: string, label: string) => {
    dispatch({ type: "view_node", node });
    dispatch({ type: "select_label", node, label });
  }, []);
  const refreshNodes = useCallback(() => bumpRefresh(), []);
  const growStub = useCallback(
    (i: number, op: string) => dispatch({ type: "grow_stub", i, op }),
    [],
  );
  const fuse = useCallback(() => dispatch({ type: "fuse" }), []);
  const setPartFilter = useCallback(
    (part: number | null) => dispatch({ type: "set_part_filter", part }),
    [],
  );
  const setDiffVs = useCallback(
    (node: string | null) => dispatch({ type: "set_diff_vs", node }),
    [],
  );
  const setSlab = useCallback(
    (slab: SlabState | null) => dispatch({ type: "set_slab", slab }),
    [],
  );
  const setViewDepth = useCallback(
    (viewDepth: Partial<ViewDepthState>) => dispatch({ type: "set_view_depth", viewDepth }),
    [],
  );
  const resetViewDepth = useCallback(
    () => dispatch({ type: "reset_view_depth" }),
    [],
  );

  const value = useMemo<CrystalContextValue>(
    () => ({
      state,
      project,
      comparisonInfo, sceneReady, cameras, reflectionEvidenceAllowed,
      beginComparison, comparisonSide, endComparison,
      viewNode,
      followLatest,
      setMode,
      setDrawStyle,
      setGrowLevel,
      toggleElem,
      setSuperN,
      setPackRadius,
      setPackRange,
      setComplete,
      setGrowAll,
      toggleOverlay,
      setIso,
      setMapKind,
      select,
      locate,
      inspectInteraction,
      clearInspection,
      selectLabel,
      refreshNodes,
      growStub,
      fuse,
      setPartFilter,
      setDiffVs,
      setSlab,
      setViewDepth,
      resetViewDepth,
    }),
    [
      state,
      project,
      comparisonInfo, sceneReady, cameras, reflectionEvidenceAllowed,
      beginComparison, comparisonSide, endComparison,
      viewNode,
      followLatest,
      setMode,
      setDrawStyle,
      setGrowLevel,
      toggleElem,
      setSuperN,
      setPackRadius,
      setPackRange,
      setComplete,
      setGrowAll,
      toggleOverlay,
      setIso,
      setMapKind,
      select,
      locate,
      inspectInteraction,
      clearInspection,
      selectLabel,
      refreshNodes,
      growStub,
      fuse,
      setPartFilter,
      setDiffVs,
      setSlab,
      setViewDepth,
      resetViewDepth,
    ],
  );

  return (
    <CrystalContext.Provider value={value}>{children}</CrystalContext.Provider>
  );
}
