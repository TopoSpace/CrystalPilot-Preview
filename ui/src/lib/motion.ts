import { useEffect, useState, useSyncExternalStore } from "react";

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export interface MotionPreference {
  reducedMotion: boolean;
  pageVisible: boolean;
  animationsEnabled: boolean;
}

export function motionEnabled(reducedMotion: boolean, pageVisible: boolean): boolean {
  return !reducedMotion && pageVisible;
}

export function motionDuration(durationMs: number, reducedMotion: boolean): number {
  return reducedMotion ? 0 : Math.max(0, durationMs);
}

export function motionScrollBehavior(reducedMotion: boolean): ScrollBehavior {
  return reducedMotion ? "auto" : "smooth";
}

/** Camera centering changes position/zoom, not orientation. Unlike 3Dmol's
 * internal zoom timer this transition can be cancelled on hide or unmount. */
export function animateView(
  from: number[], to: number[], durationMs: number, apply: (view: number[]) => void,
): () => void {
  if (durationMs <= 0) {
    apply(to);
    return () => {};
  }
  const started = performance.now();
  let frame = 0;
  let cancelled = false;
  const tick = (now: number) => {
    if (cancelled) return;
    const progress = Math.min(1, Math.max(0, (now - started) / durationMs));
    apply(to.map((value, i) => from[i] + (value - from[i]) * progress));
    if (!cancelled && progress < 1) frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => {
    cancelled = true;
    cancelAnimationFrame(frame);
  };
}

function readReducedMotion(): boolean {
  return typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function readPageVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

const listeners = new Set<() => void>();
let detach: (() => void) | null = null;
const snapshot = () => (readReducedMotion() ? 1 : 0) | (readPageVisible() ? 2 : 0);
const serverSnapshot = () => 2;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    const query = typeof window.matchMedia === "function" ? window.matchMedia(REDUCED_MOTION_QUERY) : null;
    const change = () => {
      document.documentElement.toggleAttribute("data-page-hidden", !readPageVisible());
      listeners.forEach((notify) => notify());
    };
    query?.addEventListener("change", change);
    document.addEventListener("visibilitychange", change);
    change();
    detach = () => {
      query?.removeEventListener("change", change);
      document.removeEventListener("visibilitychange", change);
      document.documentElement.removeAttribute("data-page-hidden");
    };
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      detach?.();
      detach = null;
    }
  };
}

/** Shared listeners for JS motion and the CSS background-page pause. */
export function useMotionPreference(): MotionPreference {
  const value = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const reducedMotion = (value & 1) !== 0;
  const pageVisible = (value & 2) !== 0;
  return { reducedMotion, pageVisible, animationsEnabled: motionEnabled(reducedMotion, pageVisible) };
}

/** A wall-clock sample that stops scheduling renders in a hidden tab and
 * catches up to real elapsed time once the tab is visible again. */
export function useActiveNow(active: boolean, pageVisible: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || !pageVisible) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, pageVisible]);
  return now;
}
