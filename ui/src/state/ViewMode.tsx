/** Global 简洁/详细 display density (spec P1-6, 两档 only - more tiers is
 * itself complexity). 简洁 = today's default folded view; 详细 = every
 * mechanism 「details」 (raw commands, tool payloads, work groups) starts
 * expanded, for expert audit / debugging. Persisted in localStorage so the
 * choice survives reloads. Folding stays reversible either way，详细 never
 * deletes structure, it only flips the default open state (benchmark-honesty
 * rule: 简洁 must not be implemented by dropping data).
 *
 * Components apply it via `open={verbose || undefined}` on the <details>:
 * a mode switch changes the prop, so React writes the DOM once in either
 * direction; within a mode the prop is stable, so manual per-item toggles
 * are never fought. */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ViewMode = "concise" | "verbose";

const STORAGE_KEY = "cp.viewMode";

/** Minimal storage surface so tests can pass a Map-backed stub. */
export interface KVStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function defaultStore(): KVStore | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // storage blocked (privacy mode / sandboxed iframe)
  }
}

export function loadViewMode(store: KVStore | null = defaultStore()): ViewMode {
  try {
    return store?.getItem(STORAGE_KEY) === "verbose" ? "verbose" : "concise";
  } catch {
    return "concise";
  }
}

export function saveViewMode(
  mode: ViewMode,
  store: KVStore | null = defaultStore(),
): void {
  try {
    store?.setItem(STORAGE_KEY, mode);
  } catch {
    /* non-fatal: the toggle still works for this session */
  }
}

interface ViewModeCtx {
  mode: ViewMode;
  /** convenience flag - most consumers only care about this */
  verbose: boolean;
  setMode: (mode: ViewMode) => void;
}

const Ctx = createContext<ViewModeCtx>({
  mode: "concise",
  verbose: false,
  setMode: () => undefined,
});

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ViewMode>(() => loadViewMode());
  const setMode = useCallback((m: ViewMode) => {
    setModeState(m);
    saveViewMode(m);
  }, []);
  const value = useMemo(
    () => ({ mode, verbose: mode === "verbose", setMode }),
    [mode, setMode],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useViewMode(): ViewModeCtx {
  return useContext(Ctx);
}
