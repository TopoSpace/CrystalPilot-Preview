/** Window width as React state (visual review 2026-09-04): the three-column
 * frame needs to know whether it is on a 1100 px laptop or a 1920 px
 * monitor - the sidebar becomes a drawer below NARROW_BREAKPOINT and the
 * right pane's default width scales with the window instead of staying
 * 380 px on every screen. */
import { useEffect, useState } from "react";

/** below this the sidebar is a slide-over drawer, not a column */
export const NARROW_BREAKPOINT = 1200;

function read(): number {
  return typeof window === "undefined" ? 1600 : window.innerWidth;
}

export function useViewportWidth(): number {
  const [w, setW] = useState(read);
  useEffect(() => {
    let raf = 0;
    const onResize = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        setW(read());
      });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, []);
  return w;
}

export function useNarrow(): boolean {
  return useViewportWidth() < NARROW_BREAKPOINT;
}
