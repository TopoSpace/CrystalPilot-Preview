/** Which recent projects the sidebar folds away (round-3 R2-B).
 *
 * Two kinds go under 更多: scratch projects the UI created for itself
 * (ui-import-<epoch>, unless someone named them) and projects the user hid
 * by hand. Hiding is a browser-local preference - it says nothing about the
 * project, so it does not belong in the project's settings. */
import { useCallback, useState } from "react";

const KEY = "cp.hiddenProjects";

/** Case- and separator-insensitive path key (Windows paths arrive both ways). */
export function hideKey(path: string): string {
  return path.replaceAll("\\", "/").replace(/\/+$/, "").toLowerCase();
}

export function readHidden(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    const arr: unknown = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : [],
    );
  } catch {
    return new Set();
  }
}

export function writeHidden(set: ReadonlySet<string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify([...set]));
  } catch {
    /* storage unavailable: the fold still works this session */
  }
}

/** The UI's own imports are named ui-import-<epoch ms>; a display name
 * promotes one back to the main list. */
export function isScratchProject(path: string, displayName?: string | null): boolean {
  if (displayName && displayName.trim() !== "") return false;
  const last = hideKey(path).split("/").pop() ?? "";
  return /^ui-import-\d+$/.test(last);
}

export function splitRecent<T extends { path: string; display_name?: string | null }>(
  rows: readonly T[],
  hidden: ReadonlySet<string>,
  limit: number,
): { primary: T[]; more: T[] } {
  const primary: T[] = [];
  const more: T[] = [];
  for (const r of rows) {
    if (hidden.has(hideKey(r.path)) || isScratchProject(r.path, r.display_name)) more.push(r);
    else primary.push(r);
  }
  // the cap only trims the main list; what falls off it is still reachable
  return { primary: primary.slice(0, limit), more: [...primary.slice(limit), ...more] };
}

export function useHiddenProjects(): [ReadonlySet<string>, (path: string) => void] {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(readHidden);
  const toggle = useCallback((path: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      const k = hideKey(path);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      writeHidden(next);
      return next;
    });
  }, []);
  return [hidden, toggle];
}
