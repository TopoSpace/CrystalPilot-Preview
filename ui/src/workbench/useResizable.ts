/** Mouse-draggable panel widths (user-requested): pointer-capture drag on a
 * slim edge handle, persisted to localStorage per panel key. Double-click
 * resets to the default. */
import { useCallback, useRef, useState, type PointerEvent } from "react";
import { useViewportWidth } from "./useViewport";

/** A fixed default, or one computed from the window width (visual review
 * 2026-09-04: a 380 px right pane on a 1920 px monitor left the structure -
 * the visual subject - in a strip). A width the user has dragged is kept;
 * double-click clears it and returns to the responsive default. */
export type DefaultWidth = number | ((viewportWidth: number) => number);

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

function loadStored(key: string, min: number, max: number): number | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw !== null) {
      const n = Number(raw);
      if (Number.isFinite(n)) return clamp(n, min, max);
    }
  } catch {
    /* storage unavailable */
  }
  return null;
}

function resolveDefault(def: DefaultWidth, vw: number, min: number, max: number): number {
  return clamp(typeof def === "function" ? def(vw) : def, min, max);
}

export interface ResizableEdge {
  width: number;
  /** spread onto the handle element */
  handleProps: {
    onPointerDown: (e: PointerEvent<HTMLElement>) => void;
    onDoubleClick: () => void;
  };
  dragging: boolean;
}

/**
 * @param key localStorage key, e.g. "wb.sidebarWidth"
 * @param edge which edge of the PANEL the handle sits on: dragging a
 *   "right"-edge handle rightward grows the panel; a "left"-edge handle
 *   grows it leftward (right-hand pane).
 */
export function useResizable(
  key: string,
  def: DefaultWidth,
  min: number,
  max: number,
  edge: "left" | "right",
): ResizableEdge {
  const vw = useViewportWidth();
  // the stored (dragged) width wins; without one the width follows the
  // window, which is what a fresh install on any monitor should do
  const [stored, setStored] = useState<number | null>(() => loadStored(key, min, max));
  const [dragW, setDragW] = useState<number | null>(null);
  const width = dragW ?? stored ?? resolveDefault(def, vw, min, max);
  const setWidth = (v: number | ((w: number) => number)) => {
    setDragW((cur) => {
      const base = cur ?? width;
      return typeof v === "function" ? v(base) : v;
    });
  };
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ startX: number; startW: number } | null>(null);

  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const el = e.currentTarget;
      el.setPointerCapture(e.pointerId);
      drag.current = { startX: e.clientX, startW: width };
      setDragging(true);
      const sign = edge === "right" ? 1 : -1;

      const onMove = (ev: globalThis.PointerEvent) => {
        if (!drag.current) return;
        const dx = ev.clientX - drag.current.startX;
        setWidth(clamp(drag.current.startW + sign * dx, min, max));
      };
      const onUp = () => {
        drag.current = null;
        setDragging(false);
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", onUp);
        el.removeEventListener("pointercancel", onUp);
        // persist the final value (setWidth's arg above already clamped)
        setDragW((w) => {
          const final = w ?? width;
          try {
            window.localStorage.setItem(key, String(final));
          } catch {
            /* storage unavailable */
          }
          setStored(final);
          return null;
        });
      };
      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", onUp);
      el.addEventListener("pointercancel", onUp);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, min, max, edge, width],
  );

  const onDoubleClick = useCallback(() => {
    // back to the responsive default: forget the dragged width
    setDragW(null);
    setStored(null);
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* storage unavailable */
    }
  }, [key]);

  return {
    width,
    dragging,
    handleProps: { onPointerDown, onDoubleClick },
  };
}
