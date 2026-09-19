/** Remembered open/closed state for a collapsible panel section.
 *
 * Persisted per section id so the pane comes back the way the user left
 * it - a panel that refolds itself on every reload trains people to stop
 * folding it, which defeats the point of having sections at all. */
import { useState } from "react";

export function useSection(
  id: string,
  defaultOpen = false,
): [boolean, () => void] {
  const key = `cp.sect.${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen; // private mode / storage disabled
    }
  });
  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(key, o ? "0" : "1");
      } catch {
        /* not persisting is fine; folding still works this session */
      }
      return !o;
    });
  };
  return [open, toggle];
}
