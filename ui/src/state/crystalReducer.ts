/** Pure reducer for the crystal pane (P2): node graph, viewed node + follow
 * mode, scene/map fetch status, overlays and selection.
 *
 * Follow semantics: while `follow` is true the pane tracks the backend's
 * active node (auto-jumping when the agent commits a new one). Viewing any
 * other node pins the pane to history (follow=false) and shows a banner with
 * a "back to latest" action.
 */
import type { MapKind } from "../lib/wbApi";
import { comparisonSelection } from "../lib/structureComparison";
import {
  exactSelectionInScene,
  findRenderedInteraction,
  overlayForInteraction,
  type InteractionInstance,
} from "../lib/analysisInspector";
import type { DeliveryMark,
  DataBlockResponse,
  PeakEntry,
  VoidsResponse,
  RefineNode,
  SceneAtom,
  SceneResponse,
  UniqueInteractionRow,
} from "../lib/wbTypes";

/** What SLICE of the crystal is drawn. Growing is deliberately not one of
 * these: it is an action applied to whichever slice is on screen (Olex2:
 * you `pack` a cell and then `grow` from it), so it lives in growLevel. */
export type CrystalMode = "asu" | "cell" | "super" | "radius" | "range";

/** Fractional box for mode="range" (Olex2 `pack a1 a2 b1 b2 c1 c2`). */
export interface PackRange {
  lo: [number, number, number];
  hi: [number, number, number];
}
export const DEFAULT_PACK_RANGE: PackRange = { lo: [-0.5, -0.5, -0.5], hi: [1.5, 1.5, 1.5] };
export const PACK_RADIUS_MIN = 1;
export const PACK_RADIUS_MAX = 30;

/** Shells of symmetry completion accumulated by pressing 生长. 0 = the
 * slice as the mode built it. Each press adds one shell (Olex2 `grow -s`),
 * which is why this is a level and not a switch - the BFS stops on its own
 * when nothing new appears, so a discrete molecule completes well before
 * the cap while a framework never does. */
export type GrowLevel = 0 | 1 | 2 | 3 | 4;
export const MAX_GROW_LEVEL = 4;

/** Supercell edge in unit cells. */
export type SuperN = 2 | 3 | 4;

/** How atoms are DRAWN, Olex2's mutually exclusive representations. This
 * was a lone 椭球 on/off toggle, which could only say "ORTEP or the
 * default" - there was no way to ask for a wireframe on a supercell where
 * ball-and-stick is a solid mass, or for spacefill to see a pore close up.
 * ORTEP stays the default: a reviewer looks at ADPs first. */
export type DrawStyle = "wire" | "ball" | "ellipsoid" | "space";

export interface CrystalOverlays {
  polyhedra: boolean;
  map: boolean;
  diff: boolean;
  spin: boolean;
  /** atom labels on non-H atoms (Olex2 F3) */
  labels: boolean;
  /** interaction layer (R2.3, chem/interactions.py): each kind is its own
   * pill; any of them on requests interactions=1 from the scene builder */
  hbonds: boolean;
  ixPipi: boolean;
  ixChpi: boolean;
  ixChx: boolean;
  ixHalogen: boolean;
  ixAnionPi: boolean;
  /** clickable dangling grow directions (Olex2 mode grow) */
  stubs: boolean;
  /** publication figure style: white bg, thicker bonds, dark labels */
  pub: boolean;
  /** discrete Fo−Fc Q peaks as clickable spheres (调研 P0-1) */
  peaks: boolean;
  /** solvent-accessible void isosurface + per-void stats (调研 P0-2) */
  voids: boolean;
  /** tint disorder PART groups distinct colors + occupancy labels (P1) */
  parts: boolean;
  /** short vdW contacts + contact grow stubs (P2-2, Olex2 grow -s) */
  contacts: boolean;
  /** space-group symmetry elements: axes/planes/centres (P2-3) */
  symm: boolean;
  /** node-linker simplified net of the analysis product (round-2 R4):
   * metal clusters as nodes, linkers as edges with their lattice shifts */
  net: boolean;
}

export type FetchStatus = "idle" | "loading" | "ok" | "error";

/** VESTA-style periodic slab clip (P2-4): atoms whose wrapped fractional
 * coordinate along `axis` falls outside center±thickness/2 are hidden. */
export interface SlabState {
  axis: 0 | 1 | 2;
  center: number;
  thickness: number;
}

/** Camera-depth controls. This is deliberately separate from `SlabState`:
 * slab is a scientific fractional section, while these are camera-space
 * visibility settings supplied directly to 3Dmol's fog and clip APIs. */
export interface ViewDepthState {
  fog: boolean;
  /** fraction of the clip span at which distance fog begins */
  fogStart: number;
  /** symmetric camera clip span as a fraction of the full atom extent */
  clip: number;
}

export const VIEW_FOG_START_MIN = 0.2;
export const VIEW_FOG_START_MAX = 0.9;
export const VIEW_CLIP_MIN = 0.1;
export const VIEW_CLIP_MAX = 1;
export const DEFAULT_VIEW_DEPTH: Readonly<ViewDepthState> = Object.freeze({
  fog: false,
  fogStart: 0.55,
  clip: 1,
});

function finiteClamp(value: number, fallback: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : fallback));
}

export function normalizeViewDepth(value: ViewDepthState): ViewDepthState {
  return {
    fog: value.fog === true,
    fogStart: finiteClamp(
      value.fogStart,
      DEFAULT_VIEW_DEPTH.fogStart,
      VIEW_FOG_START_MIN,
      VIEW_FOG_START_MAX,
    ),
    clip: finiteClamp(value.clip, DEFAULT_VIEW_DEPTH.clip, VIEW_CLIP_MIN, VIEW_CLIP_MAX),
  };
}

export interface CrystalSelection {
  atom: SceneAtom;
  /** index into scene.atoms */
  index: number;
}

export interface CrystalInspection {
  node: string;
  /** Canonical identity; the matching display instance is resolved per scene. */
  row: UniqueInteractionRow;
  instance?: InteractionInstance;
}

interface ComparisonSideState {
  selection: CrystalSelection | null;
  inspection: CrystalInspection | null;
  grown: { i: number; op: string }[];
}

export interface CrystalComparison {
  node: string;
  baseline: string;
  returnView: { node: string; follow: boolean; diff: boolean; diffVs: string | null };
  sides: Record<string, ComparisonSideState>;
}

export interface CrystalState {
  comparison: CrystalComparison | null;
  sceneRequestKey: string | null;
  sceneDataKey: string | null;
  selectionRestore: { node: string; selection: CrystalSelection } | null;
  nodes: RefineNode[];
  /** nodes a write_outputs delivered, from the results manifests */
  deliveries: DeliveryMark[];
  activeNode: string | null;
  activeBranch: string | null;
  branches: Record<string, string>;
  nodesStatus: FetchStatus;
  /** node id currently shown in the pane (null until first nodes load) */
  viewNode: string | null;
  follow: boolean;
  mode: CrystalMode;
  drawStyle: DrawStyle;
  /** shells grown on top of `mode`, accumulated by pressing 生长 */
  growLevel: GrowLevel;
  /** element symbols hidden from the scene (Olex2's element row). H is
   * seeded on entering a packed view, where H clutter dominates. */
  hiddenElems: string[];
  /** edge for mode="super", remembered the same way */
  superN: SuperN;
  /** sphere for mode="radius" (Olex2 pack r): Å and the ASU atom at its
   * centre (null = the ASU centroid) */
  packRadius: number;
  packCenter: string | null;
  /** fractional box for mode="range" */
  packRange: PackRange;
  /** Olex2 grow -w: after growing, every operator already used is
   * applied to the whole ASU so companions (solvent, counter-ions) come
   * along. Reset by a new slice like growth is. */
  complete: boolean;
  /** Olex2 `grow` (no arguments): grow until a symmetry element repeats
   * within the fragment - finite molecules complete, periodic nets stop
   * after one period (the scene's `grow_all` block says which). Reset by
   * a new slice like growth is. */
  growAll: boolean;
  overlays: CrystalOverlays;
  /** isosurface level for the density overlay, e Å⁻³ */
  iso: number;
  scene: SceneResponse | null;
  /** the node `scene` was built for (round-3 R6: an anchor click must not
   * select in the previous node's scene while the new one loads) */
  sceneNode: string | null;
  sceneStatus: FetchStatus;
  sceneError: string | null;
  /** which density map the overlay shows: residual Fo−Fc or 2Fo−Fc */
  mapKind: MapKind;
  /** map buffer for mapNode+mapKind (kept alongside a per-node cache) */
  mapBuffer: ArrayBuffer | null;
  mapNode: string | null;
  mapStatus: FetchStatus;
  /** Q-peak table for peaksNode (fractional sites + heights) */
  peaks: PeakEntry[] | null;
  peaksNode: string | null;
  peaksStatus: FetchStatus;
  /** void metadata + binarized CCP4 buffer for voidsNode */
  voidsMeta: VoidsResponse | null;
  voidBuffer: ArrayBuffer | null;
  voidsNode: string | null;
  voidsStatus: FetchStatus;
  /** Reflection-data block recovered for a node that committed without
   * one (`node.data === null`). Kept beside the nodes rather than merged
   * into them, because it is a weaker claim - recomputed from the
   * project's CURRENT hkl, not from what this node was fitted against. */
  dataBlock: DataBlockResponse | null;
  dataBlockNode: string | null;
  selection: CrystalSelection | null;
  /** Analysis row whose exact display instance is being inspected. */
  inspection: CrystalInspection | null;
  /** Incremented only when an external row asks the viewer to center. */
  focusRequest: number;
  /** round-3 R6: an atom label to select once the scene of `node` is
   * loaded (a transcript anchor clicked before its node's scene exists) */
  pendingSelect: { node: string; label: string } | null;
  /** user-grown symmetry instances from clicked grow stubs (mode-grow) */
  grown: { i: number; op: string }[];
  /** show only this disorder PART (null = all) */
  partFilter: number | null;
  /** diff baseline node for any-vs-any comparison (null = parent) */
  diffVs: string | null;
  /** periodic slab clip for pore cross-sections (null = off) */
  slab: SlabState | null;
  /** camera fog/clip; unlike slab this never changes which atoms exist */
  viewDepth: ViewDepthState;
}

export type CrystalAction =
  | { type: "nodes_loading" }
  | {
      type: "nodes_ok";
      nodes: RefineNode[];
      deliveries?: DeliveryMark[];
      activeNode: string | null;
      activeBranch: string | null;
      branches: Record<string, string>;
    }
  | { type: "nodes_error" }
  | { type: "view_node"; node: string }
  | { type: "begin_comparison"; baseline: string | null }
  | { type: "comparison_side"; node: string }
  | { type: "end_comparison" }
  | { type: "follow_latest" }
  | { type: "set_mode"; mode: CrystalMode }
  | { type: "set_draw_style"; style: DrawStyle }
  | { type: "set_grow_level"; level: GrowLevel }
  | { type: "toggle_elem"; elem: string }
  | { type: "set_super_n"; n: SuperN }
  | { type: "set_pack_radius"; radius: number; center: string | null }
  | { type: "set_pack_range"; range: PackRange }
  | { type: "set_complete"; complete: boolean }
  | { type: "set_grow_all"; growAll: boolean }
  | { type: "toggle_overlay"; overlay: keyof CrystalOverlays }
  | { type: "set_iso"; iso: number }
  | { type: "set_map_kind"; kind: MapKind }
  | { type: "scene_loading"; key?: string }
  | { type: "scene_ok"; scene: SceneResponse; key?: string }
  | { type: "scene_error"; error: string; key?: string }
  | { type: "map_loading" }
  | { type: "map_ok"; node: string; buffer: ArrayBuffer }
  | { type: "map_error" }
  | { type: "peaks_loading" }
  | { type: "peaks_ok"; node: string; peaks: PeakEntry[] }
  | { type: "peaks_error" }
  | {
      type: "voids_ok";
      node: string;
      meta: VoidsResponse;
      buffer: ArrayBuffer | null;
    }
  | { type: "voids_loading" }
  | { type: "voids_error" }
  | { type: "data_block_ok"; node: string; block: DataBlockResponse }
  | { type: "select"; selection: CrystalSelection | null }
  | { type: "locate"; node: string; selection: CrystalSelection }
  | { type: "inspect_interaction"; node: string; row: UniqueInteractionRow; instance?: InteractionInstance }
  | { type: "clear_inspection" }
  | { type: "select_label"; node: string; label: string }
  | { type: "grow_stub"; i: number; op: string }
  | { type: "fuse" }
  | { type: "set_part_filter"; part: number | null }
  | { type: "set_diff_vs"; node: string | null }
  | { type: "set_slab"; slab: SlabState | null }
  | { type: "set_view_depth"; viewDepth: Partial<ViewDepthState> }
  | { type: "reset_view_depth" };

export function initialCrystalState(): CrystalState {
  return {
    comparison: null,
    sceneRequestKey: null,
    sceneDataKey: null,
    selectionRestore: null,
    nodes: [],
    deliveries: [],
    activeNode: null,
    activeBranch: null,
    branches: {},
    nodesStatus: "idle",
    viewNode: null,
    follow: true,
    mode: "asu",
    drawStyle: "ellipsoid",
    growLevel: 0,
    hiddenElems: [],
    superN: 2,
    packRadius: 8,
    packCenter: null,
    packRange: DEFAULT_PACK_RANGE,
    complete: false,
    growAll: false,
    overlays: {
      polyhedra: true,
      map: false,
      diff: false,
      spin: false,
      labels: false,
      // off by default: the interaction engine runs on the whole drawn
      // range (+ halo) and the old free D···A layer it replaces drew
      // geometry-only contacts nobody had asked for
      hbonds: false,
      ixPipi: false,
      ixChpi: false,
      ixChx: false,
      ixHalogen: false,
      ixAnionPi: false,
      stubs: false,
      pub: false,
      peaks: false,
      voids: false,
      parts: false,
      contacts: false,
      symm: false,
      net: false,
    },
    iso: 0.35,
    scene: null,
    sceneNode: null,
    sceneStatus: "idle",
    sceneError: null,
    mapKind: "fofc",
    mapBuffer: null,
    mapNode: null,
    mapStatus: "idle",
    peaks: null,
    peaksNode: null,
    peaksStatus: "idle",
    voidsMeta: null,
    voidBuffer: null,
    voidsNode: null,
    voidsStatus: "idle",
    dataBlock: null,
    dataBlockNode: null,
    selection: null,
    inspection: null,
    focusRequest: 0,
    pendingSelect: null,
    grown: [],
    partFilter: null,
    diffVs: null,
    slab: null,
    viewDepth: { ...DEFAULT_VIEW_DEPTH },
  };
}

export function sceneMatchesRequest(state: CrystalState, key: string): boolean {
  return state.sceneStatus === "ok" && state.scene !== null
    && state.sceneNode === state.viewNode && state.sceneDataKey === key;
}

function comparisonSide(state: CrystalState): ComparisonSideState {
  return { selection: state.selection, inspection: state.inspection, grown: state.grown };
}

function exitComparison(state: CrystalState): CrystalState {
  if (!state.comparison) return state;
  const { returnView, sides } = state.comparison;
  const node = returnView.follow ? state.activeNode : returnView.node;
  const side = node === state.viewNode ? comparisonSide(state) : node ? sides[node] : null;
  return {
    ...state, comparison: null, viewNode: node, follow: returnView.follow,
    selection: side?.selection ?? null, inspection: side?.inspection ?? null,
    selectionRestore: node && node !== state.sceneNode && side?.selection ? { node, selection: side.selection } : null,
    grown: side?.grown ?? [], pendingSelect: null,
    diffVs: returnView.diffVs, overlays: { ...state.overlays, diff: returnView.diff },
  };
}

export function crystalReducer(
  state: CrystalState,
  action: CrystalAction,
): CrystalState {
  switch (action.type) {
    case "nodes_loading":
      return { ...state, nodesStatus: "loading" };

    case "nodes_ok": {
      const next: CrystalState = {
        ...state,
        nodes: action.nodes,
        deliveries: action.deliveries ?? [],
        activeNode: action.activeNode,
        activeBranch: action.activeBranch,
        branches: action.branches,
        nodesStatus: "ok",
      };
      const known = (id: string | null): boolean =>
        id !== null && action.nodes.some((n) => n.id === id);
      if (state.comparison && (!known(state.comparison.node) || !known(state.comparison.baseline))) {
        const exited = exitComparison(next);
        return known(exited.viewNode) ? exited : { ...exited, viewNode: action.activeNode, follow: true,
          selection: null, inspection: null, pendingSelect: null, selectionRestore: null, grown: [] };
      }
      if (state.follow || !known(state.viewNode)) {
        next.viewNode = action.activeNode;
        next.follow = true;
      }
      if (next.viewNode !== state.viewNode) {
        next.selection = null;
        next.inspection = null;
        next.pendingSelect = null;
        next.selectionRestore = null;
        next.grown = [];
      }
      return next;
    }

    case "nodes_error":
      return { ...state, nodesStatus: "error" };

    case "begin_comparison": {
      const node = state.comparison?.node ?? state.viewNode;
      const baseline = action.baseline ?? state.nodes.find((item) => item.id === node)?.parent;
      if (!node || !baseline || node === baseline
        || !state.nodes.some((item) => item.id === node)
        || !state.nodes.some((item) => item.id === baseline)) return state;
      const sides = { ...state.comparison?.sides };
      if (state.viewNode) sides[state.viewNode] = comparisonSide(state);
      return {
        ...state, viewNode: node, follow: false, pendingSelect: null, selectionRestore: null,
        selection: sides[node]?.selection ?? null,
        inspection: sides[node]?.inspection ?? null, grown: sides[node]?.grown ?? [],
        diffVs: null, overlays: { ...state.overlays, diff: false },
        comparison: { node, baseline,
          returnView: state.comparison?.returnView ?? { node, follow: state.follow,
            diff: state.overlays.diff, diffVs: state.diffVs },
          sides: Object.fromEntries([node, baseline].flatMap((id) => sides[id] ? [[id, sides[id]]] : [])),
        },
      };
    }

    case "comparison_side": {
      const pair = state.comparison;
      if (!pair || action.node === state.viewNode
        || (action.node !== pair.node && action.node !== pair.baseline)) return state;
      const sides = { ...pair.sides };
      if (state.viewNode) sides[state.viewNode] = comparisonSide(state);
      const next = sides[action.node];
      return {
        ...state, comparison: { ...pair, sides }, viewNode: action.node, follow: false,
        selection: next?.selection ?? null,
        inspection: next?.inspection ?? null,
        grown: next?.grown ?? [], pendingSelect: null, selectionRestore: null,
      };
    }

    case "end_comparison":
      return exitComparison(state);

    case "view_node": {
      if (state.comparison) return crystalReducer(exitComparison(state), action);
      if (action.node === state.viewNode) return state;
      return {
        ...state,
        viewNode: action.node,
        follow: action.node === state.activeNode,
        selectionRestore: null,
        selection: null,
        inspection: null,
        grown: [],
      };
    }

    case "follow_latest":
      return {
        ...exitComparison(state),
        follow: true,
        viewNode: state.activeNode,
        selectionRestore: null,
        selection: null,
        inspection: null,
        grown: [],
      };

    case "set_mode": {
      if (action.mode === state.mode) return state;
      const bulky =
        action.mode === "cell" || action.mode === "super" || action.mode === "range";
      const others = state.hiddenElems.filter((e) => e !== "H");
      return {
        ...state,
        mode: action.mode,
        selectionRestore: null,
        comparison: state.comparison ? { ...state.comparison, sides: Object.fromEntries(
          Object.entries(state.comparison.sides).map(([node, side]) => [node, { ...side, grown: [] }]),
        ) } : null,
        // H clutter dominates packed views; auto-hide there, show
        // otherwise. Only H is touched - an element the user hid on
        // purpose stays hidden across a repack.
        hiddenElems: bulky ? [...others, "H"] : others,
        selection: null,
        // a new slice starts ungrown, like Olex2 `pack`: carrying two
        // shells of growth into a supercell would explode the scene
        growLevel: 0,
        grown: [],
        complete: false,
        growAll: false,
      };
    }

    // the two parametrised slices: picking one both names the slice and
    // sets its parameter, so a single menu item does the whole job
    case "set_pack_radius": {
      const radius = Math.max(PACK_RADIUS_MIN, Math.min(PACK_RADIUS_MAX, action.radius));
      if (
        state.mode === "radius" &&
        state.packRadius === radius &&
        state.packCenter === action.center
      ) {
        return state;
      }
      const base =
        state.mode === "radius"
          ? state
          : crystalReducer(state, { type: "set_mode", mode: "radius" });
      return { ...base, packRadius: radius, packCenter: action.center };
    }

    case "set_pack_range": {
      const base =
        state.mode === "range"
          ? state
          : crystalReducer(state, { type: "set_mode", mode: "range" });
      return { ...base, packRange: action.range };
    }

    case "set_complete":
      return action.complete === state.complete
        ? state
        : { ...state, complete: action.complete };

    case "set_grow_all":
      return action.growAll === state.growAll
        ? state
        : { ...state, growAll: action.growAll };

    case "set_draw_style":
      return action.style === state.drawStyle
        ? state
        : { ...state, drawStyle: action.style };

    // Growing does NOT clear `grown` or the selection. The accumulated
    // shells and the hand-clicked fragments are independent (the server
    // takes `extra` on top of any hops), and stepping growth up and down
    // around the atom you are looking at must keep it selected - that is
    // the whole point of a button you press repeatedly.
    case "set_grow_level":
      return action.level === state.growLevel
        ? state
        : { ...state, growLevel: action.level };

    case "toggle_elem": {
      const has = state.hiddenElems.includes(action.elem);
      return {
        ...state,
        hiddenElems: has
          ? state.hiddenElems.filter((e) => e !== action.elem)
          : [...state.hiddenElems, action.elem],
      };
    }

    case "set_super_n":
      return action.n === state.superN
        ? state
        : { ...state, mode: "super", superN: action.n };

    case "toggle_overlay": {
      const next = {
        ...state,
        overlays: {
          ...state.overlays,
          [action.overlay]: !state.overlays[action.overlay],
        },
      };
      // turning the diff overlay off also drops a pinned baseline
      if (action.overlay === "diff" && state.overlays.diff) {
        next.diffVs = null;
      }
      return next;
    }

    case "set_diff_vs":
      return {
        ...state,
        diffVs: action.node,
        overlays: {
          ...state.overlays,
          diff: action.node !== null ? true : state.overlays.diff,
        },
      };

    case "set_iso":
      return { ...state, iso: action.iso };

    case "set_map_kind": {
      if (action.kind === state.mapKind) return state;
      return {
        ...state,
        mapKind: action.kind,
        // sensible default contour per map type (residual maps read at a
        // much lower e/A^3 level than total-density 2Fo-Fc)
        iso: action.kind === "2fofc" ? 1.5 : 0.35,
        // drop the old-kind buffer so the viewer never contours a stale
        // map at the new level while the fetch is in flight
        mapBuffer: null,
        mapNode: null,
        mapStatus: "idle",
      };
    }

    case "scene_loading":
      return { ...state, sceneStatus: "loading", sceneError: null, sceneRequestKey: action.key ?? null };

    case "scene_ok": {
      if (action.key && action.key !== state.sceneRequestKey) return state;
      if (action.scene.node && action.scene.node !== state.viewNode) return state;
      // Pending transcript anchors retain their legacy ASU fallback. Analysis
      // rows do not: they resolve only to a display instance with the same
      // operator and identity fields in this exact scene.
      const pending =
        state.pendingSelect && state.pendingSelect.node === state.viewNode
          ? state.pendingSelect
          : null;
      const pendingIndex = pending ? atomIndexForLabel(action.scene, pending.label) : -1;
      const inspection =
        state.inspection?.node === state.viewNode ? state.inspection : null;
      const rendered = inspection
        ? findRenderedInteraction(action.scene, inspection.row, inspection.instance)
        : null;
      const inspectedSelection =
        rendered?.atomIndex === null || rendered?.atomIndex === undefined
          ? null
          : {
              atom: action.scene.atoms[rendered.atomIndex],
              index: rendered.atomIndex,
            };
      const selection = pending
        ? pendingIndex >= 0
          ? { atom: action.scene.atoms[pendingIndex], index: pendingIndex }
          : null
        : inspection
          ? inspectedSelection
          : state.comparison
            ? comparisonSelection(action.scene, state.selection)
            : state.selectionRestore?.node === state.viewNode
              ? comparisonSelection(action.scene, state.selectionRestore.selection)
              : exactSelectionInScene(action.scene, state.sceneNode === state.viewNode ? state.selection : null);
      return {
        ...state,
        scene: action.scene,
        sceneNode: state.viewNode,
        sceneDataKey: action.key ?? null,
        sceneStatus: "ok",
        sceneError: null,
        selectionRestore: null,
        selection,
        inspection: inspection && rendered ? { ...inspection, instance: rendered.row } : inspection,
        focusRequest:
          inspectedSelection === null ? state.focusRequest : state.focusRequest + 1,
        pendingSelect: null,
      };
    }

    case "scene_error":
      return action.key && action.key !== state.sceneRequestKey ? state
        : { ...state, sceneStatus: "error", sceneError: action.error };

    case "grow_stub": {
      if (state.grown.length >= 64) return state; // server caps extra at 64
      if (state.grown.some((g) => g.i === action.i && g.op === action.op)) {
        return state;
      }
      return { ...state, grown: [...state.grown, { i: action.i, op: action.op }] };
    }

    case "fuse":
      return state.grown.length === 0 ? state : { ...state, grown: [] };

    case "set_part_filter":
      return state.partFilter === action.part
        ? state
        : { ...state, partFilter: action.part };

    case "set_slab":
      return { ...state, slab: action.slab };

    case "set_view_depth": {
      const viewDepth = normalizeViewDepth({ ...state.viewDepth, ...action.viewDepth });
      return viewDepth.fog === state.viewDepth.fog
        && viewDepth.fogStart === state.viewDepth.fogStart
        && viewDepth.clip === state.viewDepth.clip
        ? state
        : { ...state, viewDepth };
    }

    case "reset_view_depth":
      return state.viewDepth.fog === DEFAULT_VIEW_DEPTH.fog
        && state.viewDepth.fogStart === DEFAULT_VIEW_DEPTH.fogStart
        && state.viewDepth.clip === DEFAULT_VIEW_DEPTH.clip
        ? state
        : { ...state, viewDepth: { ...DEFAULT_VIEW_DEPTH } };

    case "map_loading":
      return { ...state, mapStatus: "loading" };

    case "map_ok":
      return {
        ...state,
        mapBuffer: action.buffer,
        mapNode: action.node,
        mapStatus: "ok",
      };

    case "map_error":
      return { ...state, mapStatus: "error" };

    case "peaks_loading":
      return { ...state, peaksStatus: "loading" };

    case "peaks_ok":
      return {
        ...state,
        peaks: action.peaks,
        peaksNode: action.node,
        peaksStatus: "ok",
      };

    case "peaks_error":
      return { ...state, peaksStatus: "error" };

    case "voids_loading":
      return { ...state, voidsStatus: "loading" };

    case "voids_ok":
      return {
        ...state,
        voidsMeta: action.meta,
        voidBuffer: action.buffer,
        voidsNode: action.node,
        voidsStatus: "ok",
      };

    case "voids_error":
      return { ...state, voidsStatus: "error" };

    case "data_block_ok":
      return {
        ...state,
        dataBlock: action.block,
        dataBlockNode: action.node,
      };

    case "select":
      if (action.selection && state.sceneNode !== state.viewNode) return state;
      return { ...state, selection: action.selection, inspection: null, pendingSelect: null, selectionRestore: null };

    case "locate": {
      if (action.node !== state.viewNode || state.sceneNode !== action.node || state.sceneStatus !== "ok" || !state.scene) return state;
      const selection = exactSelectionInScene(state.scene, action.selection);
      return {
        ...state,
        selection,
        inspection: null,
        pendingSelect: null,
        selectionRestore: null,
        focusRequest: selection ? state.focusRequest + 1 : state.focusRequest,
      };
    }

    case "inspect_interaction": {
      if (action.node !== state.viewNode) return state;
      const overlay = overlayForInteraction(action.row.kind);
      const canResolve =
        action.node === state.viewNode &&
        state.sceneNode === action.node &&
        state.sceneStatus === "ok";
      const rendered = canResolve
        ? findRenderedInteraction(state.scene, action.row, action.instance)
        : null;
      const selection =
        rendered?.atomIndex === null || rendered?.atomIndex === undefined || !state.scene
          ? null
          : {
              atom: state.scene.atoms[rendered.atomIndex],
              index: rendered.atomIndex,
            };
      return {
        ...state,
        inspection: { node: action.node, row: action.row, instance: rendered?.row ?? action.instance },
        selection,
        selectionRestore: null,
        pendingSelect: null,
        overlays: state.overlays[overlay]
          ? state.overlays
          : { ...state.overlays, [overlay]: true },
        focusRequest: selection === null ? state.focusRequest : state.focusRequest + 1,
      };
    }

    case "clear_inspection":
      return state.inspection === null
        ? state
        : { ...state, inspection: null, selection: null };

    case "select_label": {
      if (state.comparison) return crystalReducer(exitComparison(state), action);
      if (state.selectionRestore) return crystalReducer({ ...state, selectionRestore: null }, action);
      // the scene on screen belongs to the viewed node only when nothing
      // is in flight; otherwise wait for scene_ok of that node
      if (
        action.node === state.viewNode &&
        state.sceneNode === action.node &&
        state.sceneStatus === "ok" &&
        state.scene !== null
      ) {
        const i = atomIndexForLabel(state.scene, action.label);
        if (i >= 0) {
          return {
            ...state,
            selection: { atom: state.scene.atoms[i], index: i },
            inspection: null,
            pendingSelect: null,
          };
        }
        return { ...state, selection: null, inspection: null, pendingSelect: null };
      }
      return {
        ...state,
        inspection: null,
        pendingSelect: { node: action.node, label: action.label },
      };
    }

    default:
      return state;
  }
}

/** Index of the atom a transcript anchor names: `O1` is the asymmetric-unit
 * atom, `O1(-x,y,-z)` the copy generated by that operator (falling back to
 * the ASU atom when the current slice does not draw that copy). -1 = not
 * in this scene. */
export function atomIndexForLabel(scene: SceneResponse, label: string): number {
  const m = /^([^(]+?)\s*(?:\((.+)\))?\s*$/.exec(label.trim());
  if (!m) return -1;
  const base = m[1].trim().toUpperCase();
  const op = m[2]?.trim().replace(/\s+/g, "") ?? null;
  let fallback = -1;
  for (let i = 0; i < scene.atoms.length; i += 1) {
    const a = scene.atoms[i];
    if (a.label.toUpperCase() !== base) continue;
    if (op !== null) {
      if (a.sym && (a.symop ?? "").replace(/\s+/g, "") === op) return i;
      if (!a.sym && fallback < 0) fallback = i;
    } else {
      if (!a.sym) return i;
      if (fallback < 0) fallback = i;
    }
  }
  return fallback;
}
