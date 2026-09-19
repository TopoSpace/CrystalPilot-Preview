/** Floating controls for the 结构 tab (round-2 R1.2, defect D4).
 *
 * The crystal owns the pane: every control sits ON the canvas. Top-left is
 * the extent menu (what slice of the crystal is drawn and how far it has
 * been grown, in Olex2's own vocabulary: fuse / grow -s / grow / pack cell
 * / pack n / compaq). Bottom is a bar whose four group pills (绘制 / 关系 /
 * 证据 / 视图) open one panel at a time above it, with the one-shot actions
 * (带图提问 / 导出图 / 重置视角) as icons on the right. Nothing here is new
 * capability - these are the same control lines the old 45%-tall block
 * held, re-homed so the 3D view keeps the whole pane.
 */
import { clickedOutside } from "../../lib/outsideClick";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Spinner } from "../../components/ui";
import { adpAnomalies } from "../../lib/adp";
import { elementColor, partColor } from "../../lib/ellipsoid";
import { cx } from "../../lib/format";
import { zh } from "../../lib/zh";
import { useCrystal } from "../../state/CrystalProvider";
import {
  DEFAULT_PACK_RANGE,
  DEFAULT_VIEW_DEPTH,
  MAX_GROW_LEVEL,
  VIEW_CLIP_MAX,
  VIEW_CLIP_MIN,
  VIEW_FOG_START_MAX,
  VIEW_FOG_START_MIN,
  type CrystalMode,
  type CrystalOverlays,
  type DrawStyle,
  type GrowLevel,
  type PackRange,
} from "../../state/crystalReducer";
import { IconCamera, IconChevronDown, IconDownload, IconRefresh } from "../icons";
import { extentLabel, rangeLabel } from "./extent";
import { MAX_ELLIPSOID_ATOMS } from "./viewerLimits";

type OverlayId = keyof CrystalOverlays;

/** Overlays grouped by the QUESTION they answer, not by when they were
 * built: a cheap styling toggle and an expensive evidence layer never sit
 * in the same row, and each row has a caption saying what it is for. */
export const OVERLAY_GROUPS: {
  label: string;
  title?: string;
  items: { id: OverlayId; label: string; title?: string }[];
}[] = [
  {
    label: zh.grpDisplay,
    items: [
      { id: "labels", label: zh.ovLabels },
      { id: "polyhedra", label: zh.ovPolyhedra },
      { id: "parts", label: zh.ovParts, title: zh.ovPartsTip },
      { id: "pub", label: zh.ovPub, title: zh.ovPubTip },
    ],
  },
  {
    label: zh.grpRelations,
    title: zh.grpRelationsTip,
    items: [
      { id: "hbonds", label: zh.ovHbonds, title: zh.ovHbondsTip },
      { id: "ixPipi", label: zh.ovPipi, title: zh.ovPipiTip },
      { id: "ixChpi", label: zh.ovChpi, title: zh.ovChpiTip },
      { id: "ixChx", label: zh.ovChx, title: zh.ovChxTip },
      { id: "ixHalogen", label: zh.ovHalogen, title: zh.ovHalogenTip },
      { id: "ixAnionPi", label: zh.ovAnionPi, title: zh.ovAnionPiTip },
      { id: "contacts", label: zh.ovContacts, title: zh.ovContactsTip },
      { id: "stubs", label: zh.ovStubs, title: zh.ovStubsTip },
      { id: "symm", label: zh.ovSymm, title: zh.ovSymmTip },
      { id: "net", label: zh.ovNet, title: zh.ovNetTip },
    ],
  },
  {
    label: zh.grpEvidence,
    title: zh.grpEvidenceTip,
    items: [
      { id: "map", label: zh.ovMap },
      { id: "peaks", label: zh.ovPeaks, title: zh.ovPeaksTip },
      { id: "voids", label: zh.ovVoids, title: zh.ovVoidsTip },
    ],
  },
];

/** Overlay labels that are switched on, so a caption can name what a
 * coloured surface in the frame actually is. Drawn from the same table the
 * bar renders, so a new overlay cannot be forgotten here. */
export function activeLayerLabels(overlays: CrystalOverlays): string[] {
  return OVERLAY_GROUPS.flatMap((g) => g.items)
    .filter((o) => overlays[o.id])
    .map((o) => o.label);
}

// ------------------------------------------------------------------ atoms

function Pill({
  on,
  label,
  title,
  busy,
  overridden,
  disabled = false,
  tone = "accent",
  onClick,
}: {
  on: boolean;
  label: ReactNode;
  title?: string;
  busy?: boolean;
  disabled?: boolean;
  /** the toggle is on but the viewer is not honouring it (a capability
   * cliff, e.g. ellipsoids above MAX_ELLIPSOID_ATOMS). Explain it in
   * `title`; the pill stays clickable so the preference survives until
   * the scene is small enough to draw again */
  overridden?: string;
  tone?: "accent" | "warn";
  onClick: () => void;
}) {
  const lit = on && !overridden;
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      title={overridden ?? title}
      onClick={onClick}
      className={cx(
        "inline-flex h-6 items-center gap-1 rounded-pill border px-2 text-2xs font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        !lit
          ? "border-line text-ink-2 hover:bg-raised hover:text-ink"
          : tone === "warn"
            ? "border-warn/40 bg-warn/10 text-warn hover:bg-warn/15"
            : "border-accent/40 bg-accent/10 text-accent",
        overridden && "border-dashed",
      )}
    >
      {label}
      {busy && <Spinner className="h-2.5 w-2.5" />}
    </button>
  );
}

/** Segmented control over a small closed set (supercell edge, draw style).
 * Every value is visible at once rather than hidden behind a dropdown. */
function SegGroup<T extends string | number>({
  values,
  value,
  render,
  titleOf,
  struckOf,
  onPick,
}: {
  values: readonly T[];
  value: T;
  render: (v: T) => string;
  titleOf?: (v: T) => string | undefined;
  /** the value is selected but the viewer is not honouring it (capability
   * cliff): shown struck through rather than lit, so the control never
   * claims something the picture does not show */
  struckOf?: (v: T) => boolean;
  onPick: (v: T) => void;
}) {
  return (
    <span className="flex items-center rounded-md bg-raised/70 p-0.5">
      {values.map((v) => {
        const on = v === value;
        const struck = on && struckOf?.(v) === true;
        return (
          <button
            key={String(v)}
            type="button"
            aria-pressed={on}
            title={titleOf?.(v)}
            onClick={() => onPick(v)}
            className={cx(
              "h-5.5 rounded px-1.5 text-2xs font-medium whitespace-nowrap transition-colors",
              on && !struck ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink",
              struck && "line-through decoration-from-font",
            )}
          >
            {render(v)}
          </button>
        );
      })}
    </span>
  );
}

/** One labelled control line: a fixed caption column so every control
 * starts at the same x. */
function Line({
  label,
  title,
  children,
}: {
  label: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        title={title}
        className={cx(
          "w-8 shrink-0 pt-1 text-2xs leading-none text-ink-3 select-none",
          title && "cursor-help decoration-dotted underline-offset-2 hover:underline",
        )}
      >
        {label}
      </span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">{children}</div>
    </div>
  );
}

const DRAW_STYLES: { id: DrawStyle; label: string; title: string }[] = [
  { id: "wire", label: zh.drawWire, title: zh.drawWireTip },
  { id: "ball", label: zh.drawBall, title: zh.drawBallTip },
  { id: "ellipsoid", label: zh.drawEllipsoid, title: zh.drawEllipsoidTip },
  { id: "space", label: zh.drawSpace, title: zh.drawSpaceTip },
];

const SUPER_NS = [2, 3, 4] as const;

/** Close on Escape and on a pointer-down outside `ref`. */
function useDismiss(ref: React.RefObject<HTMLElement | null>, open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: PointerEvent) => {
      if (clickedOutside(ref.current, e)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const trigger = ref.current?.querySelector<HTMLButtonElement>('button[aria-expanded="true"]');
      e.preventDefault();
      e.stopPropagation();
      onClose();
      trigger?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, onClose]);
}

// ------------------------------------------------------------ extent menu

export interface ExtentItem {
  id: string;
  label: string;
  /** Olex2 equivalent, or an explicit local display limit. */
  hint: string;
  title?: string;
  active?: boolean;
  disabled?: boolean;
  /** draws a rule above the item */
  section?: boolean;
  /** group heading drawn above the item (范围 / 动作) */
  sectionLabel?: string;
  run: () => void;
}

/** The extent/grow menu as data, so the tests can check which items are
 * offered and enabled for a given state without rendering. */
export interface ExtentState {
  mode: CrystalMode;
  growLevel: number;
  superN: number;
  grown: unknown[];
  complete: boolean;
  growAll: boolean;
  packRadius: number;
  packCenter: string | null;
  /** label of the selected atom, the natural centre of a radius pack */
  selectionLabel: string | null;
}

export interface ExtentActions {
  setMode: (m: CrystalMode) => void;
  setGrowLevel: (l: GrowLevel) => void;
  setSuperN: (n: 2 | 3 | 4) => void;
  setPackRadius: (radius: number, center: string | null) => void;
  setPackRange: (range: PackRange) => void;
  setComplete: (complete: boolean) => void;
  setGrowAll: (growAll: boolean) => void;
  fuse: () => void;
  assemble: () => void;
}

/** Radii offered by the menu (Olex2 `pack r`); the centre is the selected
 * atom when there is one, else the ASU centroid. */
export const PACK_RADII = [8, 16] as const;

export function extentItems(s: ExtentState, act: ExtentActions): ExtentItem[] {
  const grownAny = s.growLevel > 0 || s.grown.length > 0 || s.complete || s.growAll;
  const atMax = s.growLevel >= MAX_GROW_LEVEL;
  // 范围 - which slice of the crystal is drawn (Olex2 fuse / pack). A slice
  // is a picture; growing is an action done to that picture, so the two
  // are separate groups (the 2026-09-05 review found them interleaved and
  // the difference between "晶胞" and "长一层" lost in one long column).
  const items: ExtentItem[] = [
    {
      id: "asu",
      label: zh.modeAsu,
      hint: "fuse",
      sectionLabel: zh.extentSecRange,
      active: s.mode === "asu" && !grownAny,
      run: () => {
        act.setMode("asu");
        act.setGrowLevel(0);
        act.setComplete(false);
        act.fuse();
      },
    },
    {
      id: "cell",
      label: zh.modeCell,
      hint: "pack cell",
      active: s.mode === "cell",
      run: () => act.setMode("cell"),
    },
  ];
  for (const n of SUPER_NS) {
    items.push({
      id: `super${n}`,
      label: `${zh.modeSuper} ${n}×${n}×${n}`,
      hint: `pack 0 ${n}`,
      active: s.mode === "super" && s.superN === n,
      // setSuperN alone is a no-op when n is already the stored edge (the
      // reducer only switches mode on a CHANGE of n), so name the slice first
      run: () => {
        act.setMode("super");
        act.setSuperN(n);
      },
    });
  }
  const centre = s.selectionLabel;
  for (const r of PACK_RADII) {
    items.push({
      id: `radius${r}`,
      label: `${zh.modeRadius} ${r} Å · ${centre ?? zh.packRadiusAsu}`,
      hint: `pack ${r}`,
      active: s.mode === "radius" && s.packRadius === r && s.packCenter === centre,
      run: () => act.setPackRadius(r, centre),
    });
  }
  items.push({
    id: "range",
    label: `${zh.modeRange} ${rangeLabel(DEFAULT_PACK_RANGE)}`,
    hint: "pack -0.5 1.5",
    active: s.mode === "range",
    run: () => act.setPackRange(DEFAULT_PACK_RANGE),
  });
  // 动作 - what is done to the slice on screen (Olex2 grow / fuse / compaq)
  items.push({
    id: "grow1",
    label: zh.growShell,
    hint: "grow -s",
    section: true,
    sectionLabel: zh.extentSecAction,
    disabled: atMax,
    run: () => act.setGrowLevel(Math.min(MAX_GROW_LEVEL, s.growLevel + 1) as GrowLevel),
  });
  items.push({
    id: "growAll",
    label: zh.growAll,
    hint: "grow",
    title: zh.growAllTip,
    active: s.growAll,
    run: () => act.setGrowAll(!s.growAll),
  });
  items.push({
    id: "complete",
    label: zh.growComplete,
    hint: "grow -w",
    title: zh.growCompleteTip,
    active: s.complete,
    run: () => act.setComplete(!s.complete),
  });
  if (grownAny) {
    items.push({
      id: "fuse",
      label: zh.fuse,
      hint: "fuse",
      title: zh.fuseTip,
      run: () => {
        act.setGrowLevel(0);
        act.setComplete(false);
        act.setGrowAll(false);
        act.fuse();
      },
    });
  }
  items.push({
    id: "assemble",
    label: zh.assembleAsu,
    hint: "compaq -a",
    title: zh.assembleAsuTip,
    section: true,
    run: act.assemble,
  });
  return items;
}

export function ExtentMenu({ onAssemble }: { onAssemble: () => void }) {
  const {
    state,
    setMode,
    setGrowLevel,
    setSuperN,
    setPackRadius,
    setPackRange,
    setComplete,
    setGrowAll,
    fuse,
  } = useCrystal();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, open, () => setOpen(false));

  const items = extentItems(
    { ...state, selectionLabel: state.selection?.atom.label ?? null },
    {
      setMode,
      setGrowLevel,
      setSuperN,
      setPackRadius,
      setPackRange,
      setComplete,
      setGrowAll,
      fuse,
      assemble: onAssemble,
    },
  );
  const atMax = state.growLevel >= MAX_GROW_LEVEL;

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          title={zh.extentMenuTip}
          onClick={() => setOpen((v) => !v)}
          className={cx(
            "flex h-7 items-center gap-1 rounded-pill border border-line bg-bg/90 py-1 pr-1.5 pl-2.5 text-xs font-medium text-ink shadow-sm backdrop-blur-sm transition-colors hover:bg-raised",
            open && "bg-raised",
          )}
        >
          <span className="max-w-[12rem] truncate">{extentLabel(state)}</span>
          <IconChevronDown size={13} className="text-ink-3" />
        </button>
        {/* one-press grow stays outside the menu: it is the action pressed
         * again and again (Olex2: grow, grow, grow) */}
        <button
          type="button"
          disabled={atMax}
          title={atMax ? zh.growAtMaxTip : zh.growOnceTip}
          onClick={() => setGrowLevel((state.growLevel + 1) as GrowLevel)}
          className={cx(
            "h-7 rounded-pill border px-2.5 text-xs font-medium shadow-sm backdrop-blur-sm transition-colors",
            atMax
              ? "cursor-not-allowed border-line bg-bg/90 text-ink-3/50"
              : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/20",
          )}
        >
          ＋{zh.growOnce}
        </button>
      </div>
      {open && (
        <div
          role="menu"
          className="absolute top-full left-0 z-20 mt-1 max-h-[min(24rem,calc(100cqh-4rem))] w-60 overflow-y-auto overscroll-contain rounded-card border border-line bg-bg p-1 shadow-lg"
        >
          {items.map((it) => (
            <Fragment key={it.id}>
              {it.sectionLabel && (
                <div
                  role="presentation"
                  className={cx(
                    "px-2 pb-0.5 text-2xs font-medium text-ink-3 select-none",
                    it.section ? "mt-1 border-t border-line pt-1.5" : "pt-0.5",
                  )}
                >
                  {it.sectionLabel}
                </div>
              )}
              <button
                role="menuitem"
                type="button"
                disabled={it.disabled}
                title={it.title}
                aria-current={it.active ? "true" : undefined}
                onClick={() => {
                  it.run();
                  setOpen(false);
                }}
                className={cx(
                  "flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-xs transition-colors",
                  it.section && !it.sectionLabel && "mt-1 border-t border-line pt-1",
                  it.disabled
                    ? "cursor-not-allowed text-ink-3/50"
                    : it.active
                      ? "bg-accent/10 text-accent"
                      : "text-ink hover:bg-raised",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{it.label}</span>
                <span className="shrink-0 font-mono text-2xs text-ink-3">{it.hint}</span>
              </button>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- panels

/** Map kind + isosurface level. Its own component so the slider's draft
 * state re-renders this line alone. */
function MapControls() {
  const { state, setIso, setMapKind } = useCrystal();
  const [isoDraft, setIsoDraft] = useState<number | null>(null);
  const commit = () => {
    if (isoDraft !== null) {
      setIso(isoDraft);
      setIsoDraft(null);
    }
  };
  return (
    <div className="flex items-center gap-2 text-2xs text-ink-3">
      <span className="flex shrink-0 items-center rounded-md bg-raised/70 p-0.5">
        {(
          [
            ["fofc", zh.mapKindFofc, zh.mapKindFofcTip],
            ["2fofc", zh.mapKind2fofc, zh.mapKind2fofcTip],
          ] as const
        ).map(([kind, label, tip]) => (
          <button
            key={kind}
            type="button"
            aria-pressed={state.mapKind === kind}
            title={tip}
            onClick={() => {
              setMapKind(kind);
              setIsoDraft(null);
            }}
            className={cx(
              "h-5 rounded px-1.5 text-2xs font-medium whitespace-nowrap transition-colors",
              state.mapKind === kind ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </span>
      <span className="shrink-0">
        {zh.isoLabel} {state.mapKind === "fofc" ? "±" : ""}
        {(isoDraft ?? state.iso).toFixed(2)}
      </span>
      <input
        type="range"
        min={state.mapKind === "2fofc" ? 0.5 : 0.2}
        max={state.mapKind === "2fofc" ? 5.0 : 1.5}
        step={state.mapKind === "2fofc" ? 0.1 : 0.05}
        value={isoDraft ?? state.iso}
        onChange={(e) => setIsoDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        className="h-1 min-w-0 flex-1 accent-(--color-accent)"
      />
      <span className="shrink-0">eÅ⁻³</span>
      {state.mapStatus === "loading" && <Spinner className="h-3 w-3 shrink-0" />}
    </div>
  );
}

function DrawPanel() {
  const { state, setDrawStyle, toggleElem, toggleOverlay, setPartFilter } = useCrystal();

  // Olex2's element visibility row, built from the scene so it only offers
  // elements that are present, ordered by count
  const elems = useMemo(() => {
    const n = new Map<string, number>();
    for (const a of state.scene?.atoms ?? []) n.set(a.elem, (n.get(a.elem) ?? 0) + 1);
    return [...n.entries()]
      .sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
      .map(([elem, count]) => ({ elem, count }));
  }, [state.scene]);

  // disorder PART chips appear only when the scene actually has parts;
  // mean occupancy per part doubles as the 同屏异色 legend
  const parts = useMemo(() => {
    const acc = new Map<number, { sum: number; n: number }>();
    for (const a of state.scene?.atoms ?? []) {
      if (!a.part) continue;
      const e = acc.get(a.part) ?? { sum: 0, n: 0 };
      e.sum += a.occ;
      e.n += 1;
      acc.set(a.part, e);
    }
    return [...acc.entries()]
      .map(([p, { sum, n }]) => ({ p, occ: sum / n }))
      .sort((x, y) => x.p - y.p);
  }, [state.scene]);

  const tooBig = (state.scene?.atoms.length ?? 0) > MAX_ELLIPSOID_ATOMS;
  const cappedNote = `${zh.ovCapped}（${state.scene?.atoms.length} > ${MAX_ELLIPSOID_ATOMS}）`;

  return (
    <>
      <Line label={zh.drawStyleLabel}>
        <SegGroup
          values={DRAW_STYLES.map((d) => d.id)}
          value={state.drawStyle}
          render={(v) => DRAW_STYLES.find((d) => d.id === v)?.label ?? v}
          titleOf={(v) =>
            tooBig && v === "ellipsoid" ? cappedNote : DRAW_STYLES.find((d) => d.id === v)?.title
          }
          struckOf={(v) => tooBig && v === "ellipsoid"}
          onPick={setDrawStyle}
        />
      </Line>
      {elems.length > 0 && (
        <Line label={zh.elemLabel} title={zh.elemTip}>
          {elems.map(({ elem, count }) => {
            const hidden = state.hiddenElems.includes(elem);
            return (
              <button
                key={elem}
                type="button"
                aria-pressed={!hidden}
                title={`${elem} × ${count}`}
                onClick={() => toggleElem(elem)}
                className={cx(
                  "inline-flex h-5.5 items-center gap-1 rounded-pill border px-1.5 font-mono text-2xs font-medium transition-colors",
                  hidden
                    ? "border-line text-ink-3/50 line-through decoration-from-font hover:text-ink-3"
                    : "border-line bg-raised/60 text-ink hover:bg-raised",
                )}
              >
                {/* the element colour as a swatch, not as text colour: white
                 * (H) and pale yellow (S) are unreadable as glyphs on a
                 * light background */}
                <span
                  aria-hidden
                  className="inline-block h-2 w-2 rounded-full border border-ink/20"
                  style={{ backgroundColor: hidden ? "transparent" : elementColor(elem) }}
                />
                {elem}
              </button>
            );
          })}
        </Line>
      )}
      <Line label={zh.grpDisplay}>
        {OVERLAY_GROUPS[0].items.map((o) => (
          <Pill
            key={o.id}
            on={state.overlays[o.id]}
            label={o.label}
            title={o.title}
            overridden={state.overlays[o.id] && tooBig && o.id === "labels" ? cappedNote : undefined}
            onClick={() => toggleOverlay(o.id)}
          />
        ))}
      </Line>
      {parts.length > 0 && (
        <Line label={zh.partFilterLabel}>
          {[null, ...parts].map((entry) => {
            const p = entry === null ? null : entry.p;
            const on = state.partFilter === p;
            const tint = state.overlays.parts && p !== null ? partColor(p) : null;
            return (
              <button
                key={p === null ? "all" : p}
                type="button"
                aria-pressed={on}
                onClick={() => setPartFilter(p)}
                style={tint && !on ? { color: tint, borderColor: `${tint}66` } : undefined}
                className={cx(
                  "h-5.5 rounded-pill border px-2 font-mono text-2xs transition-colors",
                  on
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-line text-ink-2 hover:bg-raised hover:text-ink",
                )}
              >
                {p === null
                  ? zh.partAll
                  : `PART ${p}${tint && entry !== null ? ` · ${entry.occ.toFixed(2)}` : ""}`}
              </button>
            );
          })}
        </Line>
      )}
    </>
  );
}

function RelationsPanel() {
  const { state, toggleOverlay } = useCrystal();
  return (
    <Line label="" title={zh.grpRelationsTip}>
      {OVERLAY_GROUPS[1].items.map((o) => (
        <Pill
          key={o.id}
          on={state.overlays[o.id]}
          label={o.label}
          title={o.title}
          onClick={() => toggleOverlay(o.id)}
        />
      ))}
    </Line>
  );
}

function EvidencePanel() {
  const { state, toggleOverlay, reflectionEvidenceAllowed } = useCrystal();
  const structureOnly = state.nodes.find((node) => node.id === state.viewNode)?.structure_only === true;
  const noReflections = structureOnly || !reflectionEvidenceAllowed;
  // these three each pull their own data the first time they are switched
  // on; showing it IN the pill is the honest version of "expensive"
  const busyOf: Partial<Record<OverlayId, boolean>> = {
    map: state.mapStatus === "loading",
    peaks: state.peaksStatus === "loading",
    voids: state.voidsStatus === "loading",
  };
  return (
    <>
      <Line label="" title={zh.grpEvidenceTip}>
        {OVERLAY_GROUPS[2].items.map((o) => (
          <Pill
            key={o.id}
            on={state.overlays[o.id] && !(noReflections && o.id !== "voids")}
            label={o.label}
            title={noReflections && o.id !== "voids" ? "该节点反射来源未确认" : o.title}
            disabled={noReflections && o.id !== "voids"}
            busy={busyOf[o.id] && state.overlays[o.id] && !(noReflections && o.id !== "voids")}
            onClick={() => toggleOverlay(o.id)}
          />
        ))}
      </Line>
      {state.overlays.map && !noReflections && <MapControls />}
      {noReflections && <div className="text-xs text-ink-3">{structureOnly ? zh.structureNeedsReflections : "反射来源未确认；仍可查看结构"}</div>}
    </>
  );
}

function ViewPanel() {
  const {
    state,
    toggleOverlay,
    setSlab,
    setViewDepth,
    resetViewDepth,
    beginComparison,
  } = useCrystal();
  // slab sliders commit on release (each change pays a full scene restyle)
  const [slabDraft, setSlabDraft] = useState<{ center: number; thickness: number } | null>(null);
  const commitSlab = () => {
    if (slabDraft && state.slab) {
      setSlab({ ...state.slab, ...slabDraft });
      setSlabDraft(null);
    }
  };
  return (
    <>
      <Line label="">
        <Pill
          on={state.slab !== null}
          label={zh.ovSlab}
          title={zh.ovSlabTip}
          onClick={() => {
            setSlabDraft(null);
            setSlab(state.slab === null ? { axis: 2, center: 0.25, thickness: 0.3 } : null);
          }}
        />
        <Pill on={state.overlays.spin} label={zh.ovSpin} onClick={() => toggleOverlay("spin")} />
        <button type="button" data-comparison-entry="parent"
          disabled={!!state.comparison || !state.nodes.find((node) => node.id === state.viewNode)?.parent}
          onClick={() => beginComparison()}
          className="h-7 rounded-pill border border-line px-2 text-xs text-ink-2 hover:bg-raised disabled:cursor-not-allowed disabled:opacity-40">
          与父节点对比
        </button>
      </Line>
      <Line label="相机" title="相机远雾与前后裁切；不改变晶体或分数剖面">
        <Pill
          on={state.viewDepth.fog}
          label="远雾"
          title="仅淡化远处显示，不是景深"
          onClick={() => setViewDepth({ fog: !state.viewDepth.fog })}
        />
        <button
          type="button"
          disabled={
            state.viewDepth.fog === DEFAULT_VIEW_DEPTH.fog
            && state.viewDepth.fogStart === DEFAULT_VIEW_DEPTH.fogStart
            && state.viewDepth.clip === DEFAULT_VIEW_DEPTH.clip
          }
          onClick={resetViewDepth}
          className="h-6 rounded-pill border border-line px-2 text-2xs font-medium text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
        >
          重置
        </button>
      </Line>
      <div className="flex items-center gap-2 text-2xs text-ink-3">
        <span className="w-17 shrink-0 tabular-nums">
          前后 {Math.round(state.viewDepth.clip * 100)}%
        </span>
        <input
          aria-label="前后裁切"
          title="100% 显示全部原子；降低后从镜头前后对称裁切"
          type="range"
          min={VIEW_CLIP_MIN * 100}
          max={VIEW_CLIP_MAX * 100}
          step={5}
          value={state.viewDepth.clip * 100}
          onChange={(e) => setViewDepth({ clip: Number(e.target.value) / 100 })}
          className="h-1 min-w-0 flex-1 accent-(--color-accent)"
        />
        {state.viewDepth.fog && (
          <>
            <span className="shrink-0 tabular-nums">
              雾起 {Math.round(state.viewDepth.fogStart * 100)}%
            </span>
            <input
              aria-label="远雾起点"
              type="range"
              min={VIEW_FOG_START_MIN * 100}
              max={VIEW_FOG_START_MAX * 100}
              step={5}
              value={state.viewDepth.fogStart * 100}
              onChange={(e) => setViewDepth({ fogStart: Number(e.target.value) / 100 })}
              className="h-1 min-w-0 flex-1 accent-(--color-accent)"
            />
          </>
        )}
      </div>
      {state.slab !== null && (
        <div className="flex items-center gap-2 text-2xs text-ink-3">
          <span className="flex shrink-0 items-center rounded-md bg-raised/70 p-0.5">
            {([0, 1, 2] as const).map((ax) => (
              <button
                key={ax}
                type="button"
                aria-pressed={state.slab?.axis === ax}
                onClick={() => {
                  if (state.slab) setSlab({ ...state.slab, axis: ax });
                }}
                className={cx(
                  "h-5 rounded px-1.5 font-mono text-2xs font-medium transition-colors",
                  state.slab?.axis === ax ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink",
                )}
              >
                {"abc"[ax]}
              </button>
            ))}
          </span>
          <span className="shrink-0">
            {zh.slabPos} {(slabDraft?.center ?? state.slab.center).toFixed(2)}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={slabDraft?.center ?? state.slab.center}
            onChange={(e) =>
              setSlabDraft({
                center: Number(e.target.value),
                thickness: slabDraft?.thickness ?? state.slab?.thickness ?? 0.3,
              })
            }
            onPointerUp={commitSlab}
            className="h-1 min-w-0 flex-1 accent-(--color-accent)"
          />
          <span className="shrink-0">
            {zh.slabThick} {(slabDraft?.thickness ?? state.slab.thickness).toFixed(2)}
          </span>
          <input
            type="range"
            min={0.05}
            max={1}
            step={0.05}
            value={slabDraft?.thickness ?? state.slab.thickness}
            onChange={(e) =>
              setSlabDraft({
                center: slabDraft?.center ?? state.slab?.center ?? 0.25,
                thickness: Number(e.target.value),
              })
            }
            onPointerUp={commitSlab}
            className="h-1 min-w-0 flex-1 accent-(--color-accent)"
          />
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------- floating bar

type PanelId = "draw" | "rel" | "ev" | "view";

const PANELS: { id: PanelId; label: string; title?: string }[] = [
  { id: "draw", label: zh.grpDraw },
  { id: "rel", label: zh.grpRelations, title: zh.grpRelationsTip },
  { id: "ev", label: zh.grpEvidence, title: zh.grpEvidenceTip },
  { id: "view", label: zh.grpView },
];

function IconButton({
  title,
  onClick,
  tone = "muted",
  disabled = false,
  children,
}: {
  title: string;
  onClick: () => void;
  tone?: "muted" | "accent";
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-pill transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        tone === "accent"
          ? "text-accent hover:bg-accent/10"
          : "text-ink-2 hover:bg-raised hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

export function FloatingBar({
  onResetView,
  onExport,
  onAskWithView,
}: {
  onResetView: () => void;
  onExport: () => void;
  onAskWithView: () => void;
}) {
  const { state, select, setDiffVs, reflectionEvidenceAllowed, sceneReady } = useCrystal();
  const structureOnly = state.nodes.find((node) => node.id === state.viewNode)?.structure_only === true;
  const [panel, setPanel] = useState<PanelId | null>(null);
  const [anomalyCursor, setAnomalyCursor] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, panel !== null, () => setPanel(null));

  // ADP anomaly badge: count + click-to-cycle through flagged atoms via the
  // normal selection flow (the card shows the reasons)
  const anomalies = useMemo(() => adpAnomalies(state.scene?.atoms ?? []), [state.scene]);
  const cycleAnomaly = () => {
    if (anomalies.length === 0) return;
    const next = anomalies[anomalyCursor % anomalies.length];
    select({ atom: next.atom, index: next.index });
    setAnomalyCursor((c) => c + 1);
  };

  // how many switches are on in each group - the bar says it even while
  // the panel is folded, so folding never hides state
  const onCount: Record<PanelId, number> = {
    draw: OVERLAY_GROUPS[0].items.filter((o) => state.overlays[o.id]).length,
    rel: OVERLAY_GROUPS[1].items.filter((o) => state.overlays[o.id]).length,
    ev: OVERLAY_GROUPS[2].items.filter((o) => state.overlays[o.id] && (!structureOnly || o.id === "voids")).length,
    view: [state.slab !== null, state.overlays.spin, state.comparison !== null].filter(Boolean).length,
  };
  const busy =
    (!structureOnly && reflectionEvidenceAllowed && state.overlays.map && state.mapStatus === "loading") ||
    (!structureOnly && reflectionEvidenceAllowed && state.overlays.peaks && state.peaksStatus === "loading") ||
    (state.overlays.voids && state.voidsStatus === "loading");

  return (
    <div ref={ref} className="absolute inset-x-2 bottom-2 z-10 flex flex-col items-stretch gap-1">
      {panel !== null && (
        <div data-testid="viewer-control-panel"
          className="flex max-h-[calc(100cqh-5rem)] flex-col gap-1.5 overflow-y-auto overscroll-contain rounded-card border border-line bg-bg/95 p-2.5 shadow-lg backdrop-blur-sm">
          {panel === "draw" && <DrawPanel />}
          {panel === "rel" && <RelationsPanel />}
          {panel === "ev" && <EvidencePanel />}
          {panel === "view" && <ViewPanel />}
        </div>
      )}
      <div data-testid="viewer-control-bar"
        className="flex flex-wrap items-center gap-0.5 rounded-2xl border border-line bg-bg/90 px-1 py-0.5 shadow-sm backdrop-blur-sm">
        {PANELS.map((p) => {
          const open = panel === p.id;
          const n = onCount[p.id];
          return (
            <button
              key={p.id}
              type="button"
              aria-expanded={open}
              title={p.title}
              onClick={() => setPanel(open ? null : p.id)}
              className={cx(
                "flex h-6 items-center gap-1 rounded-pill px-2 text-xs font-medium whitespace-nowrap transition-colors",
                open ? "bg-raised text-ink" : "text-ink-2 hover:bg-raised/70 hover:text-ink",
              )}
            >
              {p.label}
              {n > 0 && (
                <span className="rounded-pill bg-accent/12 px-1 font-mono text-2xs leading-4 text-accent tabular-nums">
                  {n}
                </span>
              )}
              {p.id === "ev" && busy && <Spinner className="h-2.5 w-2.5" />}
            </button>
          );
        })}
        <span className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-0.5">
          {anomalies.length > 0 && (
            <Pill
              on
              tone="warn"
              title={`${zh.adpBadgeTip}\n${anomalies.map((x) => x.atom.label).join(" ")}`}
              label={`⚠ ${anomalies.length} ADP`}
              onClick={cycleAnomaly}
            />
          )}
          {state.diffVs !== null && (
            <Pill
              on
              title={zh.compareClearTip}
              label={
                <span className="font-mono">
                  {zh.compareBaselineChip} {state.diffVs} ×
                </span>
              }
              onClick={() => setDiffVs(null)}
            />
          )}
          <IconButton title={zh.askWithViewTip} tone="accent" onClick={onAskWithView}
            disabled={!sceneReady}>
            <IconCamera size={15} />
          </IconButton>
          <IconButton title={zh.exportPngTip} onClick={onExport}
            disabled={!sceneReady}>
            <IconDownload size={15} />
          </IconButton>
          <IconButton title={zh.resetView} onClick={onResetView}>
            <IconRefresh size={15} />
          </IconButton>
        </span>
      </div>
    </div>
  );
}
