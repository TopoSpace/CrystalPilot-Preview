/** Right pane (P2): tab header (结构|节点树|指标|验证|产物, pill style from P1)
 * + crystal pane body. The pane unmounts on collapse; the heavy state
 * (nodes/scene/mode/overlays) lives in the shell-level CrystalProvider so
 * reopening restores the exact view. 验证 carries the checkCIF A-count badge
 * (red when A>0). */
import { useEffect } from "react";
import { useViewportWidth } from "./useViewport";
import { useSearchParams } from "react-router-dom";
import { cx } from "../lib/format";
import { t } from "../lib/i18n";
import { CrystalPane, type CrystalTabId } from "./crystal/CrystalPane";
import { useValidationBadge } from "./crystal/ValidationPanel";
import { IconFocus, IconPanelRight } from "./icons";
import { ResizeHandle } from "./ResizeHandle";
import { useResizable } from "./useResizable";
import { PanelReveal } from "./PanelTransition";

const TABS: { id: CrystalTabId; label: string }[] = [
  { id: "structure", label: t.tabStructure },
  { id: "analysis", label: t.tabAnalysis },
  { id: "nodes", label: t.tabNodes },
  { id: "metrics", label: t.tabMetrics },
  { id: "validation", label: t.tabValidation },
  { id: "artifacts", label: t.tabArtifacts },
];

/** 聚焦: the structure takes this share of the window; the conversation
 * keeps at least FOCUS_MIN_CHAT px. */
const FOCUS_FRACTION = 0.64;
const FOCUS_MIN_CHAT = 320;

export function RightPane({ onCollapse, compact = false, open = true }: { onCollapse: () => void; compact?: boolean; open?: boolean }) {
  // Project initialization remounts the viewer; keep an early tab click intact.
  const [params, setParams] = useSearchParams();
  const tab: CrystalTabId =
    TABS.find((item) => item.id === params.get("tab"))?.id ?? "structure";
  const setTab = (next: CrystalTabId) => {
    setParams(
      (previous) => {
        const updated = new URLSearchParams(previous);
        if (next === "structure") updated.delete("tab");
        else updated.set("tab", next);
        return updated;
      },
      { replace: true },
    );
  };
  // the delivery card asks for 产物 by event (it lives in the chat column)
  useEffect(() => {
    const on = (e: Event) => {
      const want = (e as CustomEvent<string>).detail;
      const hit = TABS.find((t) => t.id === want);
      if (hit) setTab(hit.id);
    };
    window.addEventListener("cp:right-tab", on);
    return () => window.removeEventListener("cp:right-tab", on);
  });
  const aCount = useValidationBadge();
  const alertsTitle = aCount !== null ? t.shell.rightPaneAlertsTitle(aCount) : undefined;
  // default follows the window: ~30 % of it, never below the 380 px the
  // pane was designed at nor above 640 (a dragged width still wins)
  const resize = useResizable(
    "wb.rightPaneWidth",
    (vw) => Math.min(640, Math.max(380, Math.round(vw * 0.3))),
    300,
    760,
    "left",
  );
  // 聚焦 (round-3 R2-B): the structure is the visual subject, and a 380 px
  // strip is not where you study a framework. Focus widens the pane to
  // >= 64 % of the window (a wider dragged width still wins) and the shell
  // folds the sidebar into a drawer so the conversation keeps a readable
  // column. The state rides in the URL: a reload or a shared link keeps
  // it. Esc leaves it - after any open menu, which Esc closes first.
  const focus = params.get("focus") === "1";
  const setFocus = (on: boolean) =>
    setParams(
      (previous) => {
        const updated = new URLSearchParams(previous);
        if (on) updated.set("focus", "1");
        else updated.delete("focus");
        return updated;
      },
      { replace: true },
    );
  const vw = useViewportWidth();
  const width = focus
    ? Math.min(
        Math.max(Math.round(vw * FOCUS_FRACTION), resize.width),
        Math.max(FOCUS_MIN_CHAT, vw - FOCUS_MIN_CHAT),
      )
    : resize.width;
  useEffect(() => {
    if (!focus) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector('[role="menu"]')) return;
      const t = e.target as HTMLElement | null;
      if (t && t !== document.body && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      setFocus(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <PanelReveal open={open} width={compact ? vw : width} side="right" resizing={resize.dragging}>
    <aside
      style={{ width: compact ? "100%" : width }}
      data-focus={focus ? "1" : undefined}
      className="relative flex min-w-0 max-w-full shrink-0 flex-col border-l border-line bg-bg"
    >
      {!compact && <ResizeHandle edge="left" resizable={resize} />}
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-line px-3">
        <div role="group" aria-label={t.shell.rightPaneTabs}
          onKeyDown={(e) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
            const buttons = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
            const focusedIndex = buttons.indexOf(e.target as HTMLButtonElement);
            const index = focusedIndex >= 0 ? focusedIndex : TABS.findIndex((item) => item.id === tab);
            const next = e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1
              : (index + (e.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length;
            e.preventDefault();
            setTab(TABS[next].id);
            e.currentTarget.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
          }}
          className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto overscroll-contain">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              aria-pressed={t.id === tab}
              className={cx(
                "flex h-7 items-center gap-1 rounded-pill px-2 text-xs font-medium whitespace-nowrap transition-colors",
                t.id === tab
                  ? "bg-raised text-ink"
                  : "text-ink-2 hover:bg-raised/60 hover:text-ink",
              )}
            >
              {t.label}
              {t.id === "validation" && aCount !== null && (
                <span
                  className={cx(
                    "inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-pill px-1 font-mono text-2xs leading-none tabular-nums",
                    aCount > 0 ? "bg-danger text-bg" : "bg-raised text-ink-3",
                  )}
                  title={alertsTitle}
                >
                  {aCount}
                </span>
              )}
            </button>
          ))}
        </div>
        <button
          type="button"
          title={focus ? t.focusExit : t.focusEnter}
          aria-label={focus ? t.focusExit : t.focusEnter}
          aria-pressed={focus}
          data-testid="focus-toggle"
          onClick={() => setFocus(!focus)}
          className={cx(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-raised hover:text-ink",
            focus ? "bg-raised text-ink" : "text-ink-3",
          )}
        >
          <IconFocus size={16} />
        </button>
        <button
          type="button"
          title={t.collapse}
          aria-label={t.collapse}
          data-testid="right-collapse"
          onClick={onCollapse}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-3 transition-colors hover:bg-raised hover:text-ink"
        >
          <IconPanelRight size={16} />
        </button>
      </div>
      <CrystalPane tab={tab} />
    </aside>
    </PanelReveal>
  );
}
