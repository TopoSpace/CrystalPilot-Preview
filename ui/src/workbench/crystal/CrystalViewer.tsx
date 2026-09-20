/** 3Dmol renderer for scene JSON (P2). No CIF parsing - the backend sends
 * Cartesian atoms + explicit bonds + polyhedra + cell params.
 *
 * Viewer lifecycle: created once per component mount; content is rebuilt
 * with viewer.clear() on scene/overlay changes. The camera is preserved
 * across rebuilds of the same display mode (live node updates feel like the
 * crystal evolving in place), and re-fit when the mode changes.
 */
import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import { reportUiDiagnostic } from "../../lib/diagnostics";
import { t } from "../../lib/i18n";
import type { ComparisonCameras } from "../../lib/structureComparison";
import { partHiddenOf, slabHiddenOf } from "./viewerVisibility";
import { animateView, motionDuration, useMotionPreference } from "../../lib/motion";
import {
  createViewer,
  VolumeData,
  type AtomSelectionSpec,
  type GLShape,
  type GLViewer,
} from "3dmol";
import {
  cellEdges,
  cellVectors,
  fracRows,
  type Vec3,
} from "../../lib/cellMath";
import {
  ellipsoidMeshesCached,
  elementColor,
  partColor,
} from "../../lib/ellipsoid";
import { useTheme } from "../../lib/theme";
import { ORIGIN_TILES, centreMostTiles, isOriginTile, tileOffsetsCart } from "../../lib/tiles";
import type {
  InteractionKind,
  InteractionRow,
  NetEdge,
  NetNode,
  SceneRange,
  VoidEntry,
} from "../../lib/wbTypes";
import type {
  PeakEntry,
  SceneAtom,
  SceneCell,
  SceneResponse,
  SceneStub,
  VoidsResponse,
} from "../../lib/wbTypes";
import type { DrawStyle, ViewDepthState } from "../../state/crystalReducer";
import { polyhedraMeshesCached } from "./polyhedra";
import {
  MAX_ELLIPSOID_ATOMS,
  MAX_SYMMETRY_TILES,
  applyViewerDepth,
  atomDepthSpan,
  qPeakDrawPlan,
} from "./viewerLimits";

const SPIN_SPEED = 0.6;
const FIT_ZOOM = 1.2;
// how long after a fresh fit a container resize still counts as the pane
// animating open (and so re-fits) rather than the user resizing the pane
const FIT_ARM_MS = 700;
// quiet period that ends such a burst; the trailing fit lands here
const FIT_SETTLE_MS = 120;
// 50%-probability radius of the isotropic Gaussian (matches server PROB50)
const PROB50 = 1.53818;
const MEASURE_COLOR = "#06b6d4";
const HBOND_COLOR = "#f472b6";
const STUB_COLOR = "#a3a3a3";
// vdW short contacts (P2-2): slate dashed lines + teal-ghost grow stubs
const CONTACT_COLOR = "#94a3b8";
// interaction layer (R2.3): one colour per kind, dashed; a boundary partner
// (outside the drawn range) is marked by a translucent bead at its position
const IX_COLORS: Record<InteractionKind, string> = {
  hbond: HBOND_COLOR,
  pipi: "#a855f7",
  chpi: "#14b8a6",
  chx: "#38bdf8",
  halogen: "#84cc16",
  anion_pi: "#f59e0b",
};
const NO_IX_LAYERS: Readonly<Record<InteractionKind, boolean>> = Object.freeze({
  hbond: false, pipi: false, chpi: false, chx: false, halogen: false, anion_pi: false,
});
// The void / density meshes are one shape per tile, but symmetry elements
// and Q peaks are much denser. Their independent budgets live in
// viewerLimits.ts so the status UI and draw pass share the same arithmetic.

function rangeCentre(range: SceneRange | undefined): Vec3 {
  if (!range) return [0.5, 0.5, 0.5];
  return [0, 1, 2].map(
    (k) => (range.frac_lo[k] + range.frac_hi[k]) / 2,
  ) as Vec3;
}

/** "V1 17350 Å³ · 3D · LCD 28.7 Å" (voids.json v3), "V2 9 Å³" (old cache) */
function voidLabelText(v: VoidEntry): string {
  let s = `V${v.void} ${Math.round(v.volume_A3)} Å³`;
  if (typeof v.dimensionality === "number") {
    s += v.dimensionality === 0 ? ` · ${t.crystal.viewerCavity}` : ` · ${v.dimensionality}D`;
  }
  if (typeof v.lcd_A === "number") s += ` · LCD ${v.lcd_A.toFixed(1)} Å`;
  if (typeof v.pld_A === "number") s += ` · PLD ${v.pld_A.toFixed(1)} Å`;
  return s;
}
const CONTACT_STUB_COLOR = "#2dd4bf";

const DIFF_COLORS: Record<string, string> = {
  added: "#34d399",
  moved: "#f59e0b",
  element_changed: "#a78bfa",
};
const REMOVED_COLOR = "#ef4444";
const MAP_POS_COLOR = "#22c55e";
const MAP_NEG_COLOR = "#ef4444";
// 2Fo−Fc total density draws as a single blue surface (Coot convention)
const MAP_2FOFC_COLOR = "#3b82f6";
const MAP_OPACITY = 0.55;
const MAP_2FOFC_OPACITY = 0.5;
const VOID_COLOR = "#8b5cf6";
// simplified net (R4): metal-cluster nodes, branch-linker nodes, edges
const NET_NODE_COLOR = "#c15f3c";
const NET_BRANCH_COLOR = "#2e8b8b";
const NET_EDGE_COLOR = "#8a857b";
/** spheres + cylinders drawn for the net across all tiles before the
 * instancing falls back to the centre-most tiles */
const NET_SHAPE_BUDGET = 4000;
const VOID_OPACITY = 0.32;

export interface CrystalViewerProps {
  scene: SceneResponse | null;
  cameraKey?: string;
  cameras?: ComparisonCameras;
  interactive?: boolean;
  mapBuffer: ArrayBuffer | null;
  showMap: boolean;
  /** which density the buffer holds: residual Fo−Fc (green/red ± pair)
   * or total 2Fo−Fc (single blue positive surface) */
  mapKind?: "fofc" | "2fofc";
  iso: number;
  showPolyhedra: boolean;
  /** element symbols to hide (Olex2's element visibility row) */
  hiddenElems: readonly string[];
  spin: boolean;
  /** how atoms are drawn (Olex2's mutually exclusive representations) */
  drawStyle: DrawStyle;
  /** atom labels on non-H atoms (Olex2 F3) */
  showLabels: boolean;
  /** hydrogen bonds: the interaction engine's rows when the scene carries
   * them, else the legacy geometry-only D···A list */
  showHbonds: boolean;
  /** which interaction kinds to draw (R2.3); `hbond` mirrors showHbonds */
  ixLayers?: Readonly<Record<InteractionKind, boolean>>;
  onSelectInteraction?: (row: InteractionRow) => void;
  /** clickable dangling grow directions (Olex2 mode grow) */
  showStubs: boolean;
  /** show only this disorder PART (null = all) */
  partFilter?: number | null;
  /** tint each disorder PART its own color (P1 同屏异色, Olex2 part
   * colouring); labels then carry occupancies on part atoms */
  colorByPart?: boolean;
  /** publication style: white background, thicker bonds, dark labels */
  pubStyle?: boolean;
  /** increments to export the current view as a PNG download */
  exportSignal?: number;
  /** increments to hand the current frame to `onFrame` instead of the
   * download path - same pixels, different destination */
  frameSignal?: number;
  onFrame?: (dataUrl: string) => void;
  onSelectAtom: (atom: SceneAtom, index: number) => void;
  /** materialize a clicked grow stub */
  onGrowStub?: (stub: SceneStub) => void;
  /** ordered atom indices of the click-measurement chain (2=distance,
   * 3=angle, 4=torsion); dashed connectors drawn between them */
  measureChain?: number[];
  /** increments to request a camera re-fit (重置视角) */
  resetSignal: number;
  /** increments to centre the camera on atoms[centerIndex] (以选中为中心) */
  centerSignal?: number;
  centerIndex?: number | null;
  /** atoms[] index to ring with a translucent highlight sphere (配位联动) */
  highlightIndex?: number | null;
  /** atoms[] indices flagged by the ADP anomaly audit - amber shells */
  anomalyIndices?: number[];
  /** discrete Fo−Fc Q peaks (fractional sites), clickable orange spheres */
  peaks?: PeakEntry[] | null;
  onSelectPeak?: (peak: PeakEntry, index: number) => void;
  /** solvent-accessible voids: binarized CCP4 + per-void stats (调研 P0-2) */
  voids?: { buffer: ArrayBuffer | null; meta: VoidsResponse } | null;
  /** node-linker simplified net of the analysis product (round-2 R4):
   * node spheres at the cluster centroids, edges carrying their lattice
   * shift, instanced over the same tiles as the other per-cell overlays */
  net?: { nodes: NetNode[]; edges: NetEdge[] } | null;
  /** `scene.range.tiles`: the lattice translations every PER-CELL overlay
   * (voids, density map, Q peaks, symmetry elements) is instanced over, so
   * they follow the displayed slice instead of sitting in the origin cell
   * (round-2 R2.2, D7). Must be derived from the same scene object as
   * `scene` - old caches carry no range and fall back to the origin tile. */
  tiles?: readonly Vec3[];
  /** periodic slab clip (P2-4, VESTA 式孔道剖面): hide atoms outside
   * center±thickness/2 along the fractional axis; null = off */
  slab?: { axis: 0 | 1 | 2; center: number; thickness: number } | null;
  /** camera-space fog and clip; independent of the fractional slab */
  viewDepth: ViewDepthState;
  /** draw space-group symmetry elements (P2-3 对称元素) */
  showSymm?: boolean;
}

interface XYZ {
  x: number;
  y: number;
  z: number;
}

/** 3Dmol selections accept arrays for any field at runtime ("any of the
 * listed values", GLModel.atomIsSelected) - the typings only declare the
 * scalar form, hence the cast. */
function serialSel(serials: number[]): AtomSelectionSpec {
  return { serial: serials } as unknown as AtomSelectionSpec;
}

/** Every atom and nothing else. 3Dmol's zoomTo() only folds shapes (the
 * cell box, void surfaces, symmetry elements) into the bounding sphere
 * when the selection is EMPTY, so a non-empty selection that matches all
 * atoms is the "fit what is drawn" camera. */
const ALL_ATOMS = { predicate: () => true } as unknown as AtomSelectionSpec;

function toXYZ(v: [number, number, number]): XYZ {
  return { x: v[0], y: v[1], z: v[2] };
}

/** 3Dmol label handle (typings don't export the Label class). */
type GLLabel = ReturnType<GLViewer["addLabel"]>;

function partTintOf(a: SceneAtom, colorByPart: boolean): string | null {
  return colorByPart && (a.part ?? 0) !== 0 ? partColor(a.part ?? 0) : null;
}

/** Re-add a meshed isosurface at every tile except the origin one (which the
 * base shape already IS). Marching cubes over a 240x240x100 mask costs
 * ~0.4 s, so the surface is meshed ONCE and each image is a re-upload of
 * that mesh (~20 ms) - the whole reason the range contract tiles on the
 * client instead of shipping a pre-tiled grid. `geo` is private in the
 * typings but is the only handle on the mesh 3Dmol just produced; addCustom
 * reads vertexArr synchronously, which is what makes reusing one scratch
 * array across translations safe. */
function tiledIsoCopies(
  viewer: GLViewer,
  base: GLShape,
  cell: SceneCell,
  tiles: readonly Vec3[],
  style: { color: string; opacity: number },
): GLShape[] {
  const copies: GLShape[] = [];
  const offsets = tileOffsetsCart(cell, tiles);
  const meshed = base as unknown as {
    geo?: { geometryGroups?: Record<string, unknown>[] };
  };
  for (const grp of meshed.geo?.geometryGroups ?? []) {
    const n = grp.vertices as number;
    const av = grp.vertexArray as Float32Array;
    const an = grp.normalArray as Float32Array;
    const af = grp.faceArray as Uint16Array;
    if (!n || !av || !af) continue;
    const vertexArr = new Array<XYZ>(n);
    const normalArr = new Array<XYZ>(n);
    for (let i = 0; i < n; i += 1) {
      vertexArr[i] = { x: av[3 * i], y: av[3 * i + 1], z: av[3 * i + 2] };
      normalArr[i] = { x: an[3 * i], y: an[3 * i + 1], z: an[3 * i + 2] };
    }
    const faceArr = Array.from(af.subarray(0, grp.faceidx as number));
    let px = 0;
    let py = 0;
    let pz = 0;
    for (let k = 0; k < tiles.length; k += 1) {
      if (isOriginTile(tiles[k])) continue;
      const [tx, ty, tz] = offsets[k];
      for (let i = 0; i < n; i += 1) {
        const p = vertexArr[i];
        p.x += tx - px;
        p.y += ty - py;
        p.z += tz - pz;
      }
      px = tx;
      py = ty;
      pz = tz;
      copies.push(viewer.addCustom({ vertexArr, normalArr, faceArr, ...style }));
    }
  }
  return copies;
}

/** The one tile per-void / per-peak / per-element LABELS go on: repeating
 * them in all 64 images would be noise, so they stay on the origin cell -
 * or, if the range does not contain it, on its first tile. */
function labelTileOf(tiles: readonly Vec3[]): Vec3 {
  return tiles.find(isOriginTile) ?? tiles[0];
}

export function CrystalViewer({
  scene,
  cameraKey = "",
  cameras,
  interactive = true,
  mapBuffer,
  showMap,
  mapKind = "fofc",
  iso,
  showPolyhedra,
  hiddenElems,
  spin,
  drawStyle,
  showLabels,
  showHbonds,
  showStubs,
  partFilter = null,
  colorByPart = false,
  pubStyle = false,
  exportSignal = 0,
  frameSignal = 0,
  centerSignal = 0,
  centerIndex = null,
  onFrame,
  onSelectAtom,
  onGrowStub,
  measureChain = [],
  resetSignal,
  highlightIndex = null,
  anomalyIndices = [],
  peaks = null,
  onSelectPeak,
  ixLayers = NO_IX_LAYERS,
  onSelectInteraction,
  voids = null,
  net = null,
  tiles: tilesProp = ORIGIN_TILES,
  slab = null,
  viewDepth,
  showSymm = false,
}: CrystalViewerProps) {
  // a scene cached before the range contract carries none: the origin cell
  // is exactly what every per-cell overlay used to hard-code
  const tiles = tilesProp.length > 0 ? tilesProp : ORIGIN_TILES;
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const cancelCenterRef = useRef<(() => void) | null>(null);
  const prevModeRef = useRef<string | null>(null);
  const appliedCameraKeyRef = useRef("");
  const previousSceneRef = useRef<SceneResponse | null>(null);
  const cameraCacheRef = useRef(cameras);
  cameraCacheRef.current = cameras;
  const isoShapesRef = useRef<GLShape[]>([]);
  const volCacheRef = useRef(new WeakMap<ArrayBuffer, VolumeData>());
  const { theme } = useTheme();
  const motion = useMotionPreference();
  const visibleRef = useRef(motion.pageVisible);
  visibleRef.current = motion.pageVisible;
  const dark = theme === "dark";
  // Set for the per-atom checks below; the array identity is stable
  // (the reducer only replaces it on a toggle), so this memo is too.
  const hiddenSet = useMemo(() => new Set(hiddenElems), [hiddenElems]);
  const shown = useCallback(
    (elem: string) => !hiddenSet.has(elem),
    [hiddenSet],
  );
  const viewDepthRef = useRef(viewDepth);
  viewDepthRef.current = viewDepth;
  const depthAtomsRef = useRef(scene?.atoms ?? []);
  depthAtomsRef.current = scene?.atoms ?? [];
  const applyDepth = useCallback(() => {
    const viewer = viewerRef.current;
    if (viewer) {
      const span = atomDepthSpan(depthAtomsRef.current, viewer.getView());
      applyViewerDepth(viewer, viewDepthRef.current, span);
    }
  }, []);

  // 3Dmol's render() redraws the WHOLE scene, and a structural toggle runs
  // the rebuild plus all seven overlay layers in one commit - each of which
  // used to redraw. Coalesce them. A microtask (not rAF) is what keeps this
  // output-identical: it drains before the browser paints, so no frame ever
  // shows a half-updated scene.
  const renderPendingRef = useRef(false);
  // 3Dmol shares ONE OffscreenCanvas + WebGL2 context across every viewer on
  // the page (WebGL/Renderer.ts `_offscreen_singleton`) and sizes it to the
  // current viewer's canvas before each frame. A viewer that is being torn
  // down - switching projects remounts this component, since CrystalProvider
  // is keyed by the project - can therefore leave that shared canvas at 0x0,
  // and the next transferToImageBitmap() throws (Firefox: "Failed to create
  // ImageBitmap from OffscreenCanvas"). A dropped frame is not worth blanking
  // the structure pane, so: never draw into a container with no size, and
  // treat a failed frame as a dropped frame (one retry, then quiet).
  const drawFailedRef = useRef(false);
  const drawNow = useCallback(() => {
    const viewer = viewerRef.current;
    const el = containerRef.current;
    if (!viewer || !el || !visibleRef.current) return;
    if (el.clientWidth === 0 || el.clientHeight === 0) return;
    try {
      viewer.render();
      drawFailedRef.current = false;
    } catch (e) {
      // the shared canvas was mid-teardown; ask for one more frame once the
      // dust settles, and keep the pane alive either way
      if (!drawFailedRef.current) {
        drawFailedRef.current = true;
        reportUiDiagnostic("crystal-draw", e);
        requestAnimationFrame(() => {
          const v = viewerRef.current;
          const box = containerRef.current;
          if (!v || !box || !visibleRef.current || box.clientWidth === 0 || box.clientHeight === 0) return;
          try {
            v.render();
            drawFailedRef.current = false;
          } catch {
            /* keep the last good frame rather than unmount the pane */
          }
        });
      }
    }
  }, []);
  const scheduleRender = useCallback(() => {
    if (renderPendingRef.current) return;
    renderPendingRef.current = true;
    queueMicrotask(() => {
      if (!renderPendingRef.current) return; // renderNow got there first
      renderPendingRef.current = false;
      drawNow();
    });
  }, [drawNow]);
  // pngURI() reads the canvas straight out of the GL context, so export has
  // to overtake a pending coalesced draw rather than wait for it
  const renderNow = useCallback(() => {
    renderPendingRef.current = false;
    drawNow();
  }, [drawNow]);

  // Camera fit. zoomTo() traverses every atom, so a fit is expensive on a
  // supercell. The right pane animates open, which means the first fit
  // after a mode change lands on a container that is still growing; commit
  // 30ce7e6 covered that by fitting at 0/rAF/150/350 ms - four traversals
  // and four draws on EVERY mode change, and still nothing for an
  // animation that runs past 350 ms. Fit once instead, and let the
  // ResizeObserver below fire one trailing fit when the box stops moving.
  const fitDeadlineRef = useRef(0);
  const refitTimerRef = useRef<number | null>(null);
  const needsFitRef = useRef(false);
  const fitNow = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const box = containerRef.current;
    if (box && (box.clientWidth === 0 || box.clientHeight === 0)) return;
    viewer.resize();
    // Atoms only (round-3 R2-B). With an empty selection zoomTo() takes the
    // cell box and every overlay shape into the bounding sphere, so a 39 Å
    // framework cell left its asymmetric unit as a speck in the middle of
    // the canvas. Fitting the atoms fits what is actually on screen - the
    // ASU, the grown shells, or the packed cell - and a supercell scales
    // with its own largest dimension.
    viewer.zoomTo(ALL_ATOMS);
    // zoomTo(selection) silently restores 3Dmol's asymmetric slab and its
    // default distance fog. Reapply our symmetric full-atom span after
    // every fit so rotating the fitted structure cannot lose its back half.
    applyDepth();
    // zoomTo() fits the bounding sphere to the VERTICAL field of view only;
    // in a portrait canvas (the pane is 380 px wide and, since R1.2, most
    // of the window tall) the horizontal field is narrower by the aspect
    // ratio and the cell was clipped left and right. Back off by that
    // ratio so the fit is the smaller of the two.
    const el = containerRef.current;
    const aspect = el ? el.clientWidth / Math.max(1, el.clientHeight) : 1;
    viewer.zoom(FIT_ZOOM * Math.min(1, aspect));
    scheduleRender();
  }, [applyDepth, scheduleRender]);

  // Every input listed here forces viewer.clear(), which disposes each
  // overlay layer's shapes and labels wholesale - so the layers have to
  // re-add themselves after a rebuild. This counter carries that fact as a
  // single dep instead of the same ten-value superset repeated in eight dep
  // lists (commit c54c18b), where adding a rebuild trigger meant editing
  // all of them. Derived during render rather than bumped from the rebuild
  // effect: a state bump would push the layers into a second commit, and
  // React may paint between the two - every overlay would blink off on
  // every toggle.
  const rebuildRef = useRef(0);
  const rebuild = useMemo(
    () => (rebuildRef.current += 1),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      scene,
      cameraKey,
      hiddenElems,
      showPolyhedra,
      drawStyle,
      showHbonds,
      ixLayers,
      showStubs,
      partFilter,
      colorByPart,
      pubStyle,
      dark,
      slab,
    ],
  );

  // latest-value refs so the iso overlay can be applied from any effect
  const mapRef = useRef(mapBuffer);
  mapRef.current = mapBuffer;
  const showMapRef = useRef(showMap);
  showMapRef.current = showMap;
  const isoRef = useRef(iso);
  isoRef.current = iso;
  const mapKindRef = useRef(mapKind);
  mapKindRef.current = mapKind;
  const onSelectRef = useRef(onSelectAtom);
  onSelectRef.current = interactive ? onSelectAtom : () => {};
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;
  const onGrowStubRef = useRef(onGrowStub);
  onGrowStubRef.current = interactive ? onGrowStub : undefined;
  const onSelectPeakRef = useRef(onSelectPeak);
  onSelectPeakRef.current = interactive ? onSelectPeak : undefined;
  const onSelectIxRef = useRef(onSelectInteraction);
  onSelectIxRef.current = interactive ? onSelectInteraction : undefined;
  const spinRef = useRef(spin);
  spinRef.current = spin && motion.animationsEnabled && interactive;
  // read through refs so applyIso keeps a stable identity: both change only
  // with `scene`, which already bumps `rebuild` and re-applies the iso
  const tilesRef = useRef<readonly Vec3[]>(tiles);
  tilesRef.current = tiles;
  const cellRef = useRef<SceneCell | null>(scene?.cell ?? null);
  cellRef.current = scene?.cell ?? null;

  const applyIso = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of isoShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    isoShapesRef.current = [];
    const buf = mapRef.current;
    if (showMapRef.current && buf) {
      let vol = volCacheRef.current.get(buf);
      if (!vol) {
        vol = new VolumeData(buf, "ccp4");
        volCacheRef.current.set(buf, vol);
      }
      const level = isoRef.current;
      // the CCP4 covers ONE cell, so a supercell (or a fragment grown into
      // a neighbour) used to have density in the origin cell only - the
      // same defect the void surface had (R2.2, D7)
      const cell = cellRef.current;
      const tiled = tilesRef.current;
      const addSurface = (isoval: number, color: string, opacity: number) => {
        const base = viewer.addIsosurface(vol, { isoval, color, opacity });
        const copies = cell
          ? tiledIsoCopies(viewer, base, cell, tiled, { color, opacity })
          : [];
        if (!cell || tiled.some(isOriginTile)) {
          isoShapesRef.current.push(base);
        } else {
          try {
            viewer.removeShape(base); // the origin cell is outside the range
          } catch {
            /* already gone */
          }
        }
        isoShapesRef.current.push(...copies);
      };
      if (mapKindRef.current === "2fofc") {
        // total density: positive contour only - a negative 2Fo−Fc level
        // is physically meaningless at display isovalues
        addSurface(level, MAP_2FOFC_COLOR, MAP_2FOFC_OPACITY);
      } else {
        addSurface(level, MAP_POS_COLOR, MAP_OPACITY);
        addSurface(-level, MAP_NEG_COLOR, MAP_OPACITY);
      }
    }
    scheduleRender();
  }, [scheduleRender]);

  // ------------------------------------------------------- viewer lifecycle
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const viewer = createViewer(el, {
      backgroundColor: dark ? "#1a1a1a" : "#ffffff",
      // 3Dmol otherwise enables fog at 40% of its slab by default, which
      // makes the far atoms look out of focus before the user asks for it.
      disableFog: true,
    });
    viewerRef.current = viewer;
    viewer.setViewChangeCallback((view: number[]) => {
      cameraCacheRef.current?.set(appliedCameraKeyRef.current, view);
    });
    return () => {
      cameraCacheRef.current?.set(appliedCameraKeyRef.current, viewer.getView());
      viewer.setViewChangeCallback(() => {});
      cancelCenterRef.current?.();
      viewer.spin(false);
      viewer.clear();
      viewerRef.current = null;
      isoShapesRef.current = [];
      prevModeRef.current = null;
      el.innerHTML = "";
    };
    // theme handled by its own effect; viewer is created once per mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.setBackgroundColor(
      pubStyle ? "#ffffff" : dark ? "#1a1a1a" : "#ffffff",
      1,
    );
    scheduleRender();
  }, [dark, pubStyle, scheduleRender]);

  // A camera-depth change is a projection update, not a structural rebuild:
  // preserve orientation/zoom and redraw the same scientific scene.
  useEffect(() => {
    applyDepth();
    scheduleRender();
  }, [viewDepth, scene, applyDepth, scheduleRender]);

  // ---------------------------------------------------------- scene rebuild
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !scene) return;
    cancelCenterRef.current?.();

    const sameMode = prevModeRef.current === scene.mode;
    const outgoingView = viewer.getView();
    cameraCacheRef.current?.set(appliedCameraKeyRef.current, outgoingView);
    const savedView = cameraKey
      ? cameraCacheRef.current?.get(cameraKey) ?? (previousSceneRef.current === scene ? outgoingView : null)
      : sameMode ? outgoingView : null;
    appliedCameraKeyRef.current = cameraKey;
    previousSceneRef.current = scene;
    fitDeadlineRef.current = 0;
    needsFitRef.current = false;
    if (refitTimerRef.current !== null) window.clearTimeout(refitTimerRef.current);
    refitTimerRef.current = null;
    isoShapesRef.current = []; // clear() disposes them wholesale
    viewer.clear();

    // atoms with explicit bonds (constructed BEFORE addAtoms)
    const bondsByAtom: number[][] = scene.atoms.map(() => []);
    for (const [i, j] of scene.bonds) {
      if (bondsByAtom[i] && bondsByAtom[j]) {
        bondsByAtom[i].push(j);
        bondsByAtom[j].push(i);
      }
    }
    const model = viewer.addModel();
    model.addAtoms(
      scene.atoms.map((a, i) => ({
        elem: a.elem,
        x: a.xyz[0],
        y: a.xyz[1],
        z: a.xyz[2],
        serial: i,
        bonds: bondsByAtom[i],
        bondOrder: bondsByAtom[i].map(() => 1),
      })),
    );

    // publication preset: white bg, thicker bonds (Olex2 brad 0.3 analog)
    const stickR = pubStyle ? 0.16 : 0.1;
    const ellStickR = pubStyle ? 0.14 : 0.09;

    // Jmol colorscheme: 3Dmol's default palette lacks most heavy elements
    // (W falls through to DeepPink) and must match lib/ellipsoid.ts colors
    //
    // Wireframe is the one that matters at scale: a grown supercell in
    // ball-and-stick is a solid mass, and dropping the per-atom spheres is
    // what makes connectivity visible again (it is also the cheapest to
    // draw, but that is a side effect, not the reason it exists).
    // Spacefill answers a different question - whether a pore is really
    // open - which no other representation here can show.
    viewer.setStyle(
      {},
      drawStyle === "wire"
        ? { line: { colorscheme: "Jmol" } }
        : drawStyle === "space"
          ? { sphere: { colorscheme: "Jmol" } }
          : {
              stick: { radius: stickR, colorscheme: "Jmol" },
              sphere: { scale: 0.2, colorscheme: "Jmol" },
            },
    );

    const slabRows = slab ? fracRows(scene.cell) : null;
    const partHidden = (a: SceneAtom): boolean =>
      partHiddenOf(a, partFilter) || slabHiddenOf(a, slab, slabRows);
    const partTint = (a: SceneAtom): string | null =>
      partTintOf(a, colorByPart);

    // ORTEP mode: aniso atoms get true 50% ADP ellipsoid meshes (sticks
    // kept, default sphere hidden); iso atoms become 50%-probability
    // spheres of their U_eq. Falls back to ball-and-stick on huge scenes.
    const ellOn =
      drawStyle === "ellipsoid"
      && scene.atoms.length <= MAX_ELLIPSOID_ATOMS;
    if (ellOn) {
      const ellIdx: number[] = [];
      const ellTints = new Map<number, string>();
      // iso spheres bucketed by (radius, tint) so a PART tint never wipes
      // out the U_eq-scaled sphere it shares a style pass with
      const isoBuckets = new Map<
        string,
        { radius: number; tint: string | null; serials: number[] }
      >();
      scene.atoms.forEach((a, i) => {
        if (a.flag === "removed" || partHidden(a)) return;
        if (!shown(a.elem)) return;
        const tint = partTint(a);
        if (a.adp_known !== false && a.ell?.r && a.ell.m && !a.ell.npd) {
          ellIdx.push(i);
          if (tint) ellTints.set(i, tint);
        } else {
          const r = a.adp_known === false || a.u_eq === null ? (a.elem === "H" ? 0.12 : 0.2) : Math.min(
            0.5,
            Math.max(0.06, PROB50 * Math.sqrt(Math.max(a.u_eq, 0.0015))),
          );
          const key = `${Math.round(r * 50)}|${tint ?? ""}`; // 0.02 Å buckets
          const b = isoBuckets.get(key) ?? {
            radius: Math.round(r * 50) / 50,
            tint,
            serials: [],
          };
          b.serials.push(i);
          isoBuckets.set(key, b);
        }
      });
      if (ellIdx.length > 0) {
        const plain = ellIdx.filter((i) => !ellTints.has(i));
        if (plain.length > 0) {
          viewer.setStyle(serialSel(plain), {
            stick: { radius: ellStickR, colorscheme: "Jmol" },
          });
        }
        const tinted = new Map<string, number[]>();
        for (const [i, c] of ellTints) {
          const list = tinted.get(c) ?? [];
          list.push(i);
          tinted.set(c, list);
        }
        for (const [c, serials] of tinted) {
          viewer.setStyle(serialSel(serials), {
            stick: { radius: ellStickR, color: c },
          });
        }
        for (const [color, mesh] of ellipsoidMeshesCached(
          scene.atoms,
          ellIdx,
          ellTints,
        )) {
          viewer.addCustom({ ...mesh, color });
        }
      }
      for (const b of isoBuckets.values()) {
        viewer.setStyle(
          serialSel(b.serials),
          b.tint
            ? {
                stick: { radius: ellStickR, color: b.tint },
                sphere: { radius: b.radius, color: b.tint },
              }
            : {
                stick: { radius: ellStickR, colorscheme: "Jmol" },
                sphere: { radius: b.radius, colorscheme: "Jmol" },
              },
        );
      }
    } else if (colorByPart) {
      // ball-and-stick PART tint
      const byTint = new Map<string, number[]>();
      scene.atoms.forEach((a, i) => {
        if (a.flag === "removed" || partHidden(a)) return;
        if (!shown(a.elem)) return;
        const tint = partTint(a);
        if (!tint) return;
        const list = byTint.get(tint) ?? [];
        list.push(i);
        byTint.set(tint, list);
      });
      for (const [c, serials] of byTint) {
        viewer.setStyle(serialSel(serials), {
          stick: { radius: stickR, color: c },
          sphere: { scale: 0.2, color: c },
        });
      }
    }

    // diff flags (present only when the scene was fetched with diff=1)
    const byFlag = new Map<string, number[]>();
    scene.atoms.forEach((a, i) => {
      if (a.flag) {
        const list = byFlag.get(a.flag) ?? [];
        list.push(i);
        byFlag.set(a.flag, list);
      }
    });
    for (const [flag, serials] of byFlag) {
      if (flag === "removed") {
        viewer.setStyle(serialSel(serials), {
          sphere: { scale: 0.26, color: REMOVED_COLOR, opacity: 0.45 },
        });
      } else {
        const color = DIFF_COLORS[flag];
        if (color) {
          viewer.setStyle(serialSel(serials), {
            stick: { radius: 0.11, color },
            sphere: { scale: 0.26, color },
          });
        }
      }
    }

    for (const e of hiddenSet) viewer.setStyle({ elem: e }, {});

    // hide filtered-out disorder parts / slab-clipped atoms (after every
    // other style pass)
    if (partFilter !== null || slab !== null) {
      const hiddenIdx = scene.atoms
        .map((a, i) => (partHidden(a) ? i : -1))
        .filter((i) => i >= 0);
      if (hiddenIdx.length > 0) viewer.setStyle(serialSel(hiddenIdx), {});
    }

    // interaction layer (R2.3): every row carries its own endpoints, so a
    // partner outside the drawn range (boundary) is still drawn to its
    // position and marked with a bead; an H-bond is drawn H···A when the H
    // exists (Olex2), D···A otherwise; rows that fail the angle test are
    // thinner. Clicking a segment opens the geometry / criteria card.
    const ix = scene.interactions;
    if (ix) {
      for (const row of ix.rows) {
        if (!(row.kind === "hbond" ? showHbonds : ixLayers[row.kind])) continue;
        const a = row.ai !== null ? scene.atoms[row.ai] : undefined;
        const b = row.bi !== null ? scene.atoms[row.bi] : undefined;
        if (a && (partHidden(a) || !shown(a.elem))) continue;
        if (b && (partHidden(b) || !shown(b.elem))) continue;
        const color = IX_COLORS[row.kind] ?? CONTACT_COLOR;
        const start = toXYZ(row.kind === "hbond" && row.h_xyz ? row.h_xyz : row.p);
        const end = toXYZ(row.q);
        viewer.addCylinder({
          start,
          end,
          radius: row.passes ? 0.024 : 0.014,
          color,
          dashed: true,
          clickable: true,
          callback: () => onSelectIxRef.current?.(row),
        });
        if (row.kind === "pipi" || row.kind === "chpi" || row.kind === "anion_pi") {
          // ring centroids are not atoms: mark them so the segment has ends
          viewer.addSphere({ center: end, radius: 0.12, color, opacity: 0.7 });
          if (row.kind === "pipi") {
            viewer.addSphere({ center: start, radius: 0.12, color, opacity: 0.7 });
          }
        }
        if (row.boundary) {
          viewer.addSphere({ center: end, radius: 0.18, color, opacity: 0.3 });
        }
      }
    } else if (showHbonds && scene.hbonds && scene.hbonds.length > 0) {
      // legacy geometry-only D···A list (scenes fetched without the layer)
      for (const [i, j] of scene.hbonds) {
        const a = scene.atoms[i];
        const b = scene.atoms[j];
        if (!a || !b) continue;
        if (!shown(a.elem) || !shown(b.elem)) continue;
        if (partHidden(a) || partHidden(b)) continue;
        viewer.addCylinder({
          start: toXYZ(a.xyz),
          end: toXYZ(b.xyz),
          radius: 0.02,
          color: HBOND_COLOR,
          dashed: true,
        });
      }
    }

    // short vdW contacts (P2-2): dashed slate lines between materialized
    // packing neighbours (π-stacking, halogen bonds, generic close packing)
    if (scene.contacts && scene.contacts.length > 0) {
      for (const [i, j] of scene.contacts) {
        const a = scene.atoms[i];
        const b = scene.atoms[j];
        if (!a || !b || partHidden(a) || partHidden(b)) continue;
        viewer.addCylinder({
          start: toXYZ(a.xyz),
          end: toXYZ(b.xyz),
          radius: 0.016,
          color: CONTACT_COLOR,
          dashed: true,
        });
      }
    }

    // dangling grow directions (Olex2 mode grow): dashed stub toward the
    // unmaterialized symmetry mate + clickable translucent ghost; contact
    // stubs (grow -s) draw thinner in teal so packing growth reads apart
    // from covalent growth. Bond stubs follow the 生长键 toggle; contact
    // stubs only exist in the scene when the 短接触 overlay requested them.
    if (scene.stubs && scene.stubs.length > 0) {
      for (const stub of scene.stubs) {
        const contact = stub.kind === "contact";
        if (!contact && !showStubs) continue;
        const from = scene.atoms[stub.from];
        if (!from || partHidden(from)) continue;
        if (!shown(stub.elem)) continue;
        const f = from.xyz;
        const t = stub.xyz;
        const mid: [number, number, number] = [
          f[0] + (t[0] - f[0]) * 0.72,
          f[1] + (t[1] - f[1]) * 0.72,
          f[2] + (t[2] - f[2]) * 0.72,
        ];
        viewer.addCylinder({
          start: toXYZ(f),
          end: toXYZ(mid),
          radius: contact ? 0.02 : 0.035,
          color: contact ? CONTACT_STUB_COLOR : STUB_COLOR,
          dashed: true,
        });
        viewer.addSphere({
          center: toXYZ(t),
          radius: contact ? 0.2 : 0.24,
          color: contact ? CONTACT_STUB_COLOR : elementColor(stub.elem),
          opacity: contact ? 0.3 : 0.38,
          clickable: true,
          callback: () => onGrowStubRef.current?.(stub),
        });
      }
    }

    // unit-cell wireframe + labelled a/b/c axes at the origin
    // dark: zinc-600 on #1a1a1a was barely there (visual review 2026-09-05)
    const edgeColor = dark && !pubStyle ? "#8a857b" : "#a1a1aa";
    for (const [start, end] of cellEdges(scene.cell)) {
      viewer.addCylinder({
        start: toXYZ(start),
        end: toXYZ(end),
        radius: 0.025,
        color: edgeColor,
      });
    }
    const axes = cellVectors(scene.cell);
    const axisNames = ["a", "b", "c"] as const;
    const axisColors = ["#ef4444", "#22c55e", "#3b82f6"];
    axes.forEach((v, k) => {
      viewer.addLabel(axisNames[k], {
        position: { x: v[0] * 1.04, y: v[1] * 1.04, z: v[2] * 1.04 },
        fontSize: 12,
        fontColor: axisColors[k],
        backgroundOpacity: 0,
        alignment: "center",
        inFront: true,
      });
    });

    // peaks / voids / ADP-anomaly / atom-label overlays are separate
    // incremental effects (perf r12): toggling them must not pay a full
    // scene rebuild on big cells

    // coordination polyhedra: one flat-shaded mesh per metal element
    // (P2-1 - bimetallic nodes stay distinguishable)
    if (showPolyhedra && scene.polyhedra.length > 0) {
      for (const [color, mesh] of polyhedraMeshesCached(
        scene.polyhedra,
        scene.atoms,
        partHidden,
      )) {
        if (mesh.faceArr.length > 0) {
          viewer.addCustom({ ...mesh, color, opacity: 0.45 });
        }
      }
    }

    // atom picking
    viewer.setClickable({}, true, (atom: { serial?: number }) => {
      const idx = atom.serial;
      if (idx === undefined) return;
      const a = scene.atoms[idx];
      if (a) onSelectRef.current(a, idx);
    });

    if (savedView) {
      viewer.setView(savedView);
      applyDepth();
      scheduleRender();
    } else {
      needsFitRef.current = true; // deferred to the camera-fit effect below
    }
    prevModeRef.current = scene.mode;

    applyIso();
    if (spinRef.current) viewer.spin("y", SPIN_SPEED);
    // `rebuild` IS the dep list - every viewer.clear() trigger lives in the
    // useMemo that computes it, so they are declared in exactly one place
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, applyIso, applyDepth, scheduleRender]);

  // -------------------------------------------------- overlay layer effects
  // Each overlay keeps its own shape/label handles and re-adds itself after
  // any full rebuild - `rebuild` carries that (React runs effects in
  // declaration order, so the rebuild has already cleared by the time these
  // run). Toggling an overlay touches ONLY that layer - no viewer.clear(),
  // no re-styling thousands of atoms. Deps are therefore `rebuild` plus the
  // layer's own inputs, i.e. only the props the rebuild does NOT depend on.

  // atom labels (Olex2 F3): non-H, skip ghosts; symmetry copies dimmed;
  // with PART tinting on, part atoms carry occupancy in the part color
  const atomLabelsRef = useRef<GLLabel[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const l of atomLabelsRef.current) {
      try {
        viewer.removeLabel(l);
      } catch {
        /* already cleared with the scene */
      }
    }
    atomLabelsRef.current = [];
    const slabRows = scene && slab ? fracRows(scene.cell) : null;
    const hiddenL = (a: SceneAtom): boolean =>
      partHiddenOf(a, partFilter) || slabHiddenOf(a, slab, slabRows);
    // CN / mean-bond-length tag under each polyhedron's metal (P2-1);
    // few polyhedra even on big scenes, so no atom-count cap here
    if (scene && showLabels && showPolyhedra) {
      for (const poly of scene.polyhedra) {
        const m = scene.atoms[poly.metal];
        if (!m || m.flag === "removed" || hiddenL(m)) {
          continue;
        }
        const avg =
          poly.vertices.reduce(
            (s, v) =>
              s +
              Math.hypot(
                v[0] - m.xyz[0],
                v[1] - m.xyz[1],
                v[2] - m.xyz[2],
              ),
            0,
          ) / Math.max(1, poly.vertices.length);
        atomLabelsRef.current.push(
          viewer.addLabel(
            `CN${poly.vertices.length} ${avg.toFixed(2)}Å`,
            {
              position: { x: m.xyz[0], y: m.xyz[1] - 0.45, z: m.xyz[2] },
              fontSize: 10,
              fontColor: elementColor(m.elem),
              backgroundOpacity: 0,
              alignment: "center",
              inFront: true,
            },
          ),
        );
      }
    }
    if (scene && showLabels && scene.atoms.length <= MAX_ELLIPSOID_ATOMS) {
      scene.atoms.forEach((a) => {
        if (a.elem === "H" || a.flag === "removed" || hiddenL(a)) {
          return;
        }
        const darkText = dark && !pubStyle;
        const tint = partTintOf(a, colorByPart);
        atomLabelsRef.current.push(
          viewer.addLabel(tint ? `${a.label} ${a.occ.toFixed(2)}` : a.label, {
            position: toXYZ(a.xyz),
            fontSize: 11,
            fontColor: tint
              ? tint
              : darkText
                ? a.sym
                  ? "#8b8b90"
                  : "#e4e4e7"
                : a.sym
                  ? "#9f9fa5"
                  : "#27272a",
            backgroundOpacity: 0,
            alignment: "center",
            inFront: true,
          }),
        );
      });
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, showLabels, scheduleRender]);

  // Fo−Fc Q peaks (调研 P0-1): clickable orange spheres at peak sites,
  // radius scaled by height; labels on the strongest few. Independent of
  // the map isosurface overlay (peaks answer "WHERE exactly", the surface
  // "how it is shaped").
  const peakShapesRef = useRef<GLShape[]>([]);
  const peakLabelsRef = useRef<GLLabel[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of peakShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    for (const l of peakLabelsRef.current) {
      try {
        viewer.removeLabel(l);
      } catch {
        /* already cleared with the scene */
      }
    }
    peakShapesRef.current = [];
    peakLabelsRef.current = [];
    if (scene && peaks && peaks.length > 0) {
      const [va, vb, vc] = cellVectors(scene.cell);
      const cart = (f: [number, number, number]): XYZ => ({
        x: f[0] * va[0] + f[1] * vb[0] + f[2] * vc[0],
        y: f[0] * va[1] + f[1] * vb[1] + f[2] * vc[1],
        z: f[0] * va[2] + f[1] * vb[2] + f[2] * vc[2],
      });
      // the peak list is one cell's worth: instance it over the range so a
      // supercell does not show residual density in a single cell (R2.2, D7)
      // budget: one clickable sphere per peak per tile
      const positivePeaks = peaks
        .map((pk, index) => ({ pk, index }))
        .filter(({ pk }) => pk.height > 0);
      const plan = qPeakDrawPlan(positivePeaks.length, tiles.length);
      const peakTiles = plan.tileCount < tiles.length
        ? centreMostTiles(tiles, rangeCentre(scene.range), plan.tileCount)
        : tiles;
      const offsets = tileOffsetsCart(scene.cell, peakTiles);
      const labelTile = labelTileOf(peakTiles);
      positivePeaks.slice(0, plan.peaksPerTile).forEach(({ pk, index: i }) => {
        const c0 = cart(pk.site);
        offsets.forEach((off, k) => {
          const c = { x: c0.x + off[0], y: c0.y + off[1], z: c0.z + off[2] };
          peakShapesRef.current.push(
            viewer.addSphere({
              center: c,
              radius: Math.min(0.45, 0.12 + 0.1 * pk.height),
              color: "#f97316",
              opacity: 0.55,
              clickable: true,
              // any image of a peak selects the same peak
              callback: () => onSelectPeakRef.current?.(pk, i),
            }),
          );
          if (i < 12 && peakTiles[k] === labelTile) {
            peakLabelsRef.current.push(
              viewer.addLabel(`Q${i + 1} ${pk.height.toFixed(1)}`, {
                position: { x: c.x, y: c.y + 0.28, z: c.z },
                fontSize: 10,
                fontColor: "#f97316",
                backgroundOpacity: 0,
                alignment: "center",
                inFront: true,
              }),
            );
          }
        });
      });
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, peaks, scheduleRender]);

  // solvent-accessible voids (调研 P0-2): purple isosurface over the
  // binarized whole-cell mask + per-void centre labels. The mask is
  // periodic and covers one cell (Olex2 does the same), so the surface is
  // instanced over the scene's range rather than drawn once at the origin.
  const voidShapesRef = useRef<GLShape[]>([]);
  const voidLabelsRef = useRef<GLLabel[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of voidShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    for (const l of voidLabelsRef.current) {
      try {
        viewer.removeLabel(l);
      } catch {
        /* already cleared with the scene */
      }
    }
    voidShapesRef.current = [];
    voidLabelsRef.current = [];
    if (scene && voids !== null) {
      const [va, vb, vc] = cellVectors(scene.cell);
      if (voids.buffer) {
        let vol = volCacheRef.current.get(voids.buffer);
        if (!vol) {
          vol = new VolumeData(voids.buffer, "ccp4");
          volCacheRef.current.set(voids.buffer, vol);
        }
        const style = { color: VOID_COLOR, opacity: VOID_OPACITY };
        const base = viewer.addIsosurface(vol, { isoval: 0.5, ...style });
        // The mask covers ONE cell, so a supercell of atoms used to sit
        // inside a single cell of pore - channels that visibly stopped at
        // a boundary the structure does not have. The range says which
        // cells are on screen; the surface is meshed once and re-added at
        // each of them (R2.2 generalised the old n x n x n repeat).
        const copies = tiledIsoCopies(viewer, base, scene.cell, tiles, style);
        if (tiles.some(isOriginTile)) {
          voidShapesRef.current.push(base);
        } else {
          try {
            viewer.removeShape(base); // the origin cell is outside the range
          } catch {
            /* already gone */
          }
        }
        voidShapesRef.current.push(...copies);
      }
      // labels stay on ONE cell: one per void, not one per image
      const [lx, ly, lz] = tileOffsetsCart(scene.cell, [labelTileOf(tiles)])[0];
      for (const v of voids.meta.voids) {
        // the inscribed-sphere centre is defined for every void and always
        // inside the cell; the flood-fill centroid only for a cavity (D17)
        const f = v.inscribed_centre_frac ?? v.centre_frac;
        if (!f) continue;
        const pos = {
          x: lx + f[0] * va[0] + f[1] * vb[0] + f[2] * vc[0],
          y: ly + f[0] * va[1] + f[1] * vb[1] + f[2] * vc[1],
          z: lz + f[0] * va[2] + f[1] * vb[2] + f[2] * vc[2],
        };
        // volume only. The per-void electron count is the one the server
        // flags as unreliable at large solvent fractions, and putting it
        // on the picture in 11 px made it look like the authoritative
        // number - the cell total belongs in the chip, where it can carry
        // its caveat.
        voidLabelsRef.current.push(
          viewer.addLabel(voidLabelText(v), {
            position: pos,
            fontSize: 11,
            fontColor: VOID_COLOR,
            backgroundOpacity: 0,
            alignment: "center",
            inFront: true,
          }),
        );
        // channel direction arrows (R3.5): one per lattice direction the
        // void repeats along, from the inscribed centre, half a period long
        for (const d of v.directions ?? []) {
          if (d.length !== 3) continue;
          const dir = {
            x: d[0] * va[0] + d[1] * vb[0] + d[2] * vc[0],
            y: d[0] * va[1] + d[1] * vb[1] + d[2] * vc[1],
            z: d[0] * va[2] + d[1] * vb[2] + d[2] * vc[2],
          };
          const len = Math.hypot(dir.x, dir.y, dir.z);
          if (len === 0) continue;
          const half = 0.5;
          voidShapesRef.current.push(
            viewer.addArrow({
              start: { x: pos.x - dir.x * half, y: pos.y - dir.y * half, z: pos.z - dir.z * half },
              end: { x: pos.x + dir.x * half, y: pos.y + dir.y * half, z: pos.z + dir.z * half },
              radius: 0.12,
              radiusRatio: 2.5,
              mid: 0.85,
              color: VOID_COLOR,
              opacity: 0.85,
            }),
          );
        }
      }
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, voids, scheduleRender]);

  // simplified net (round-2 R4, chem/topology.py): one sphere per node at
  // its centroid and one cylinder per edge, the edge's lattice shift moving
  // its far end into the neighbouring cell - so a pcu net draws as the cube
  // frame it is. Instanced over the range tiles like the void surface; the
  // labels stay on one cell.
  const netShapesRef = useRef<GLShape[]>([]);
  const netLabelsRef = useRef<GLLabel[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of netShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    for (const l of netLabelsRef.current) {
      try {
        viewer.removeLabel(l);
      } catch {
        /* already cleared with the scene */
      }
    }
    netShapesRef.current = [];
    netLabelsRef.current = [];
    if (scene && net && net.nodes.length > 0) {
      const [va, vb, vc] = cellVectors(scene.cell);
      const cart = (f: readonly number[], t: readonly number[]) => ({
        x: (f[0] + t[0]) * va[0] + (f[1] + t[1]) * vb[0] + (f[2] + t[2]) * vc[0],
        y: (f[0] + t[0]) * va[1] + (f[1] + t[1]) * vb[1] + (f[2] + t[2]) * vc[1],
        z: (f[0] + t[0]) * va[2] + (f[1] + t[1]) * vb[2] + (f[2] + t[2]) * vc[2],
      });
      const byId = new Map(net.nodes.map((n) => [n.id, n]));
      const perTile = net.nodes.length + net.edges.length;
      const drawTiles =
        tiles.length * perTile > NET_SHAPE_BUDGET
          ? centreMostTiles(
              tiles,
              rangeCentre(scene.range),
              Math.max(1, Math.floor(NET_SHAPE_BUDGET / perTile)),
            )
          : tiles;
      for (const t of drawTiles) {
        for (const n of net.nodes) {
          const metal = n.kind === "metal_cluster";
          netShapesRef.current.push(
            viewer.addSphere({
              center: cart(n.centroid_frac, t),
              radius: metal ? 0.9 : 0.6,
              color: metal ? NET_NODE_COLOR : NET_BRANCH_COLOR,
              opacity: 0.92,
            }),
          );
        }
        for (const [a, b, sh] of net.edges) {
          const na = byId.get(a);
          const nb = byId.get(b);
          if (!na || !nb) continue;
          netShapesRef.current.push(
            viewer.addCylinder({
              start: cart(na.centroid_frac, t),
              end: cart(nb.centroid_frac, [t[0] + sh[0], t[1] + sh[1], t[2] + sh[2]]),
              radius: 0.18,
              color: NET_EDGE_COLOR,
              opacity: 0.85,
              fromCap: 1,
              toCap: 1,
            }),
          );
        }
      }
      const lt = labelTileOf(tiles);
      for (const n of net.nodes) {
        netLabelsRef.current.push(
          viewer.addLabel(`N${n.id}`, {
            position: cart(n.centroid_frac, lt),
            fontSize: 11,
            fontColor: n.kind === "metal_cluster" ? NET_NODE_COLOR : NET_BRANCH_COLOR,
            backgroundOpacity: 0,
            alignment: "center",
            inFront: true,
          }),
        );
      }
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, net, scheduleRender]);

  // space-group symmetry elements (P2-3 对称元素): rotation/screw axes
  // colored by order (screw dashed), mirror/glide planes as translucent
  // double-sided fans, inversion centres as grey dots, ITA symbol labels
  const symmShapesRef = useRef<GLShape[]>([]);
  const symmLabelsRef = useRef<GLLabel[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of symmShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    for (const l of symmLabelsRef.current) {
      try {
        viewer.removeLabel(l);
      } catch {
        /* already cleared with the scene */
      }
    }
    symmShapesRef.current = [];
    symmLabelsRef.current = [];
    if (scene && showSymm && scene.sym_elements?.length) {
      const [va, vb, vc] = cellVectors(scene.cell);
      // the elements are cell-clipped fractional geometry, so an image is
      // the same geometry shifted by the tile's integer translation - a
      // supercell used to show its symmetry only in the origin cell
      // (R2.2, D7)
      const cartAt = (f: [number, number, number], t: Vec3): XYZ => {
        const a = f[0] + t[0];
        const b = f[1] + t[1];
        const c = f[2] + t[2];
        return {
          x: a * va[0] + b * vb[0] + c * vc[0],
          y: a * va[1] + b * vb[1] + c * vc[1],
          z: a * va[2] + b * vb[2] + c * vc[2],
        };
      };
      const AXIS_COLORS: Record<number, string> = {
        2: "#f43f5e",
        3: "#22c55e",
        4: "#3b82f6",
        6: "#a855f7",
      };
      // one set of ITA symbols, not 64: labels ride the label tile only
      const symTiles =
        tiles.length > MAX_SYMMETRY_TILES
          ? centreMostTiles(tiles, rangeCentre(scene.range), MAX_SYMMETRY_TILES)
          : tiles;
      const labelTile = labelTileOf(symTiles);
      let labels = 0;
      for (const tile of symTiles) {
        const cart = (f: [number, number, number]): XYZ => cartAt(f, tile);
        const labelled = tile === labelTile;
        for (const el of scene.sym_elements) {
          if (el.kind === "axis" && el.seg) {
            const color = AXIS_COLORS[el.order ?? 2] ?? "#f43f5e";
            const a = cart(el.seg[0]);
            const b = cart(el.seg[1]);
            symmShapesRef.current.push(
              viewer.addCylinder({
                start: a,
                end: b,
                radius: el.screw ? 0.045 : 0.06,
                color,
                dashed: el.screw === true,
                opacity: 0.75,
              }),
            );
            if (el.centre) {
              symmShapesRef.current.push(
                viewer.addSphere({
                  center: cart(el.centre),
                  radius: 0.14,
                  color,
                  opacity: 0.85,
                }),
              );
            }
            if (labelled && labels < 48) {
              labels += 1;
              symmLabelsRef.current.push(
                viewer.addLabel(el.symbol, {
                  position: {
                    x: b.x + 0.12 * (b.x - a.x === 0 ? 1 : Math.sign(b.x - a.x)),
                    y: b.y + 0.25,
                    z: b.z,
                  },
                  fontSize: 10,
                  fontColor: color,
                  backgroundOpacity: 0,
                  alignment: "center",
                  inFront: true,
                }),
              );
            }
          } else if (el.kind === "plane" && el.poly && el.poly.length >= 3) {
            const verts = el.poly.map(cart);
            const vertexArr: XYZ[] = [];
            const normalArr: XYZ[] = [];
            const faceArr: number[] = [];
            const u = {
              x: verts[1].x - verts[0].x,
              y: verts[1].y - verts[0].y,
              z: verts[1].z - verts[0].z,
            };
            const w = {
              x: verts[2].x - verts[0].x,
              y: verts[2].y - verts[0].y,
              z: verts[2].z - verts[0].z,
            };
            const nv = {
              x: u.y * w.z - u.z * w.y,
              y: u.z * w.x - u.x * w.z,
              z: u.x * w.y - u.y * w.x,
            };
            const mag = Math.hypot(nv.x, nv.y, nv.z) || 1;
            const nn = { x: nv.x / mag, y: nv.y / mag, z: nv.z / mag };
            const push = (p: XYZ, n: XYZ) => {
              faceArr.push(vertexArr.length);
              vertexArr.push(p);
              normalArr.push(n);
            };
            for (let k = 1; k + 1 < verts.length; k += 1) {
              // both windings so the fan is visible from either side
              push(verts[0], nn);
              push(verts[k], nn);
              push(verts[k + 1], nn);
              const back = { x: -nn.x, y: -nn.y, z: -nn.z };
              push(verts[0], back);
              push(verts[k + 1], back);
              push(verts[k], back);
            }
            symmShapesRef.current.push(
              viewer.addCustom({
                vertexArr,
                normalArr,
                faceArr,
                color: "#eab308",
                opacity: el.glide ? 0.14 : 0.24,
              }) as GLShape,
            );
            if (labelled && labels < 48) {
              labels += 1;
              const c0 = verts.reduce(
                (s, p) => ({ x: s.x + p.x, y: s.y + p.y, z: s.z + p.z }),
                { x: 0, y: 0, z: 0 },
              );
              symmLabelsRef.current.push(
                viewer.addLabel(el.symbol, {
                  position: {
                    x: c0.x / verts.length,
                    y: c0.y / verts.length,
                    z: c0.z / verts.length,
                  },
                  fontSize: 10,
                  fontColor: "#ca8a04",
                  backgroundOpacity: 0,
                  alignment: "center",
                  inFront: true,
                }),
              );
            }
          } else if (el.kind === "point" && el.p) {
            symmShapesRef.current.push(
              viewer.addSphere({
                center: cart(el.p),
                radius: 0.11,
                color: "#9ca3af",
                opacity: 0.8,
              }),
            );
          }
        }
      }
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, showSymm, scheduleRender]);

  // ADP anomaly shells (调研 P0-3): amber translucent envelope on atoms
  // the frontend audit flagged (NPD / axis ratio / U_eq extremes)
  const anomalyShapesRef = useRef<GLShape[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of anomalyShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    anomalyShapesRef.current = [];
    if (scene) {
      const slabRows = slab ? fracRows(scene.cell) : null;
      for (const idx of anomalyIndices) {
        const a = scene.atoms[idx];
        if (
          !a ||
          a.flag === "removed" ||
          partHiddenOf(a, partFilter) ||
          slabHiddenOf(a, slab, slabRows)
        ) {
          continue;
        }
        if (!shown(a.elem)) continue;
        anomalyShapesRef.current.push(
          viewer.addSphere({
            center: toXYZ(a.xyz),
            radius: 0.55,
            color: "#f59e0b",
            opacity: 0.3,
          }),
        );
      }
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, anomalyIndices, scheduleRender]);

  // ------------------------------------------------------------- PNG export
  useEffect(() => {
    if (exportSignal === 0 || !interactive) return;
    const viewer = viewerRef.current;
    if (!viewer) return;
    try {
      renderNow(); // pngURI() grabs the canvas as-is; never let it be stale
      const uri = viewer.pngURI();
      const a = document.createElement("a");
      a.href = uri;
      a.download = `crystal_${scene?.node ?? "view"}_${scene?.mode ?? ""}.png`;
      a.click();
    } catch {
      /* canvas not ready */
    }
    // fires only on the export button (signal bump), not on scene changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exportSignal]);

  // Same capture, handed to the caller rather than to a download. What the
  // agent gets this way is the orientation, the overlays that are on and
  // what the density actually looks like there - none of which survives
  // being turned into a sentence.
  useEffect(() => {
    if (frameSignal === 0 || !interactive) return;
    const viewer = viewerRef.current;
    if (!viewer || !onFrameRef.current) return;
    try {
      renderNow();
      onFrameRef.current(viewer.pngURI());
    } catch {
      /* canvas not ready */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameSignal]);

  // ------------------------------------------------------------ map overlay
  useEffect(() => {
    applyIso();
  }, [showMap, mapBuffer, iso, mapKind, applyIso]);

  // -------------------------------------------------------------------- spin
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (spin && motion.animationsEnabled && interactive) viewer.spin("y", SPIN_SPEED);
    else viewer.spin(false);
    if (!motion.animationsEnabled || !interactive) cancelCenterRef.current?.();
    if (motion.pageVisible) {
      viewer.resize();
      scheduleRender();
    }
  }, [spin, interactive, motion.animationsEnabled, motion.pageVisible, scheduleRender]);

  // ------------------------------------------------------ selection highlight
  // Runs after the scene-rebuild effect (declaration order): viewer.clear()
  // disposes shapes wholesale, so the stale handle is removed defensively and
  // the sphere re-added on every rebuild.
  const highlightRef = useRef<GLShape | null>(null);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (highlightRef.current) {
      try {
        viewer.removeShape(highlightRef.current);
      } catch {
        /* already cleared with the scene */
      }
      highlightRef.current = null;
    }
    const atom =
      scene !== null && highlightIndex !== null
        ? scene.atoms[highlightIndex]
        : undefined;
    if (atom) {
      highlightRef.current = viewer.addSphere({
        center: toXYZ(atom.xyz),
        radius: 0.65,
        color: dark ? "#4c9eff" : "#0d78f2",
        opacity: 0.35,
      });
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, highlightIndex, scheduleRender]);

  // ------------------------------------------------- measurement connectors
  // Dashed cyan chain between clicked atoms (2=distance, 3=angle, 4=torsion;
  // the readout chip lives in CrystalPane). Runs after the scene rebuild so
  // viewer.clear() has already disposed stale shapes.
  const measureShapesRef = useRef<GLShape[]>([]);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    for (const s of measureShapesRef.current) {
      try {
        viewer.removeShape(s);
      } catch {
        /* already cleared with the scene */
      }
    }
    measureShapesRef.current = [];
    if (scene && measureChain.length >= 1) {
      for (const idx of measureChain) {
        const a = scene.atoms[idx];
        if (!a) continue;
        measureShapesRef.current.push(
          viewer.addSphere({
            center: toXYZ(a.xyz),
            radius: 0.28,
            color: MEASURE_COLOR,
            opacity: 0.5,
          }),
        );
      }
      for (let k = 0; k + 1 < measureChain.length; k += 1) {
        const a = scene.atoms[measureChain[k]];
        const b = scene.atoms[measureChain[k + 1]];
        if (!a || !b) continue;
        measureShapesRef.current.push(
          viewer.addCylinder({
            start: toXYZ(a.xyz),
            end: toXYZ(b.xyz),
            radius: 0.028,
            color: MEASURE_COLOR,
            dashed: true,
          }),
        );
      }
    }
    scheduleRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild, measureChain, scheduleRender]);

  // ------------------------------------------------------------ camera fit
  // Declared after every layer so zoomTo() sees the finished scene: overlay
  // shapes (symmetry elements, void surfaces, peak spheres) count toward the
  // bounding box, and the old 0/rAF/150/350 ms burst only picked them up by
  // accident, on its later passes.
  useEffect(() => {
    if (!needsFitRef.current) return;
    needsFitRef.current = false;
    fitNow();
    // window in which a container resize still reads as the pane animating
    // open (the ResizeObserver below takes it from here)
    fitDeadlineRef.current = Date.now() + FIT_ARM_MS;
  }, [rebuild, fitNow]);

  // -------------------------------------------------- canvas size tracking
  // 3Dmol's canvas keeps a stale size when the pane is resized/collapsed;
  // follow the container so the structure never renders letterboxed-small.
  // A deliberate resize preserves the user's view (resize only, no re-zoom)
  // only a resize inside the post-fit window re-zooms, and only once the
  // burst has gone quiet, which is what the pane-open animation looks like.
  useEffect(() => {
    const el = containerRef.current;
    if (el === null || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => {
      const v = viewerRef.current;
      if (!v || !visibleRef.current) return;
      if (el.clientWidth === 0 || el.clientHeight === 0) return;
      v.resize();
      scheduleRender();
      if (Date.now() >= fitDeadlineRef.current) return;
      if (refitTimerRef.current !== null) {
        window.clearTimeout(refitTimerRef.current);
      }
      refitTimerRef.current = window.setTimeout(() => {
        refitTimerRef.current = null;
        fitDeadlineRef.current = 0;
        if (visibleRef.current) fitNow();
      }, FIT_SETTLE_MS);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      if (refitTimerRef.current !== null) {
        window.clearTimeout(refitTimerRef.current);
        refitTimerRef.current = null;
      }
    };
  }, [fitNow, scheduleRender]);

  // ------------------------------------------------------------- reset view
  useEffect(() => {
    if (resetSignal === 0) return;
    cancelCenterRef.current?.();
    fitNow();
  }, [resetSignal, fitNow]);

  // ------------------------------------------------------ centre on atom
  // A one-atom selection gives 3Dmol its 5 Å minimum sphere: a close-up on
  // the selected atom and its first coordination shell, animated so the
  // eye keeps track of where it went. 重置视角 brings the whole scene back.
  useEffect(() => {
    if (centerSignal === 0) return;
    const viewer = viewerRef.current;
    if (!viewer || centerIndex === null || centerIndex === undefined) return;
    cancelCenterRef.current?.();
    const from = viewer.getView();
    viewer.zoomTo(serialSel([centerIndex]), 0);
    const to = viewer.getView();
    viewer.setView(from);
    // zoomTo resets the slab; cancellation may happen before the first frame.
    applyDepth();
    scheduleRender();
    cancelCenterRef.current = animateView(from, to, motionDuration(300, !motion.animationsEnabled), (view) => {
      viewer.setView(view);
      applyDepth();
      scheduleRender();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerSignal]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0"
      style={interactive ? undefined : { pointerEvents: "none" }}
      onPointerDown={() => cancelCenterRef.current?.()}
      onWheel={() => cancelCenterRef.current?.()}
    />
  );
}

// Props the memo compares. `voids` is excluded because CrystalPane builds it
// as a fresh object literal every render - it is compared by its two stable
// members instead (see below). The three callbacks are excluded because
// CrystalPane re-creates those arrows every render too; the viewer only ever
// reads them through refs, never as effect deps, so a skipped render leaves
// behind a closure that is still correct - but ONLY while CrystalPane's
// handlers capture nothing render-scoped (today: dispatch-only useCallbacks
// and functional setState). `satisfies` fails the build if a new prop is
// added without a decision here.
const COMPARED_PROPS = {
  scene: 1,
  cameraKey: 1,
  cameras: 1,
  interactive: 1,
  mapBuffer: 1,
  showMap: 1,
  mapKind: 1,
  iso: 1,
  showPolyhedra: 1,
  hiddenElems: 1,
  spin: 1,
  drawStyle: 1,
  showLabels: 1,
  showHbonds: 1,
  ixLayers: 1,
  showStubs: 1,
  partFilter: 1,
  colorByPart: 1,
  pubStyle: 1,
  exportSignal: 1,
  frameSignal: 1,
  measureChain: 1,
  resetSignal: 1,
  centerSignal: 1,
  centerIndex: 1,
  highlightIndex: 1,
  anomalyIndices: 1,
  peaks: 1,
  tiles: 1,
  slab: 1,
  viewDepth: 1,
  showSymm: 1,
  net: 1,
} satisfies Record<
  Exclude<
    keyof CrystalViewerProps,
    | "voids"
    | "onSelectAtom"
    | "onGrowStub"
    | "onSelectPeak"
    | "onFrame"
    | "onSelectInteraction"
  >,
  1
>;

function propsEqual(a: CrystalViewerProps, b: CrystalViewerProps): boolean {
  const av = a.voids ?? null;
  const bv = b.voids ?? null;
  if (av !== bv) {
    // both members outlive the wrapper: the buffer is the fetched CCP4 and
    // the meta comes straight out of the reducer
    if (!av || !bv) return false;
    if (av.buffer !== bv.buffer || av.meta !== bv.meta) return false;
  }
  const keys = Object.keys(COMPARED_PROPS) as (keyof typeof COMPARED_PROPS)[];
  for (const k of keys) {
    if (a[k] !== b[k]) return false;
  }
  return true;
}

/** Every consumer of useCrystal() re-renders on any dispatch - including the
 * 30 s node poll, which fires two. Rebuilding a supercell for that is pure
 * waste, so the lazy chunk exports the memoized component. */
export default memo(CrystalViewer, propsEqual);
