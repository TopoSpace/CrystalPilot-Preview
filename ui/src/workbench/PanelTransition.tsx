import { useLayoutEffect, useState, type ReactNode } from "react";
import { t } from "../lib/i18n";
import { useMotionPreference } from "../lib/motion";

const DURATION = 300;
const EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

/** Keep the departing content until its exit finishes; a reversed toggle
 * cancels the old removal timer and continues from the current CSS position. */
function usePresence(open: boolean) {
  const { reducedMotion } = useMotionPreference();
  const [present, setPresent] = useState(open);
  const [ready, setReady] = useState(open);
  useLayoutEffect(() => {
    let first = 0, second = 0, timer = 0;
    if (open) {
      setPresent(true);
      first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setReady(true)); });
    } else {
      setReady(false);
      if (reducedMotion) setPresent(false);
      else timer = window.setTimeout(() => setPresent(false), DURATION);
    }
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); clearTimeout(timer); };
  }, [open, reducedMotion]);
  return { present: open || present, expanded: open && (ready || reducedMotion), duration: reducedMotion ? 0 : DURATION };
}

export function PanelReveal({ open, width, side, resizing = false, children }: {
  open: boolean; width: number; side: "left" | "right"; resizing?: boolean; children: ReactNode;
}) {
  const { present, expanded, duration } = usePresence(open);
  const [unclipped, setUnclipped] = useState(open);
  useLayoutEffect(() => {
    setUnclipped(false);
    if (!open) return;
    const timer = window.setTimeout(() => setUnclipped(true), duration + 40);
    return () => window.clearTimeout(timer);
  }, [open, width, duration]);
  if (!present) return null;
  return <div data-testid={`${side}-panel-transition`} data-expanded={expanded ? "true" : "false"}
    {...{ inert: open ? undefined : "" }} aria-hidden={!open || undefined}
    className="relative h-full min-w-0 shrink-0 overflow-hidden"
    style={{ width: expanded ? width : 0, maxWidth: side === "left" ? "85vw" : "100%",
      overflow: expanded && (unclipped || resizing || duration === 0) ? "visible" : "hidden",
      transition: resizing ? "none" : `width ${duration}ms ${EASING}` }}>
    <div className="flex h-full" style={{ width,
      opacity: expanded ? 1 : 0,
      transform: expanded ? "none" : `translateX(${side === "left" ? -12 : 12}px)`,
      transition: `opacity ${duration * 0.7}ms ease, transform ${duration}ms ${EASING}` }}>
      {children}
    </div>
  </div>;
}

export function PanelDrawer({ open, side, onClose, children }: {
  open: boolean; side: "left" | "right"; onClose?: () => void; children: ReactNode;
}) {
  const { present, expanded, duration } = usePresence(open);
  if (!present) return null;
  return <div className={`absolute inset-0 ${side === "left" ? "z-40" : "z-30"}`}
    data-testid={side === "left" ? "sidebar-drawer" : "mobile-structure-pane"}
    {...{ inert: open ? undefined : "" }} aria-hidden={!open || undefined}
    style={{ pointerEvents: open ? undefined : "none" }}>
    {onClose && <button type="button" aria-label={t.closeDrawer} onClick={onClose}
      className="absolute inset-0 bg-ink/20" style={{ opacity: expanded ? 1 : 0, transition: `opacity ${duration}ms ease` }} />}
    <div className={`absolute inset-y-0 flex ${side === "left" ? "left-0 shadow-xl" : "inset-x-0 bg-bg"}`}
      data-testid={`${side}-drawer-surface`}
      style={{ transform: expanded ? "none" : `translateX(${side === "left" ? -100 : 100}%)`, transition: `transform ${duration}ms ${EASING}` }}>
      {children}
    </div>
  </div>;
}
