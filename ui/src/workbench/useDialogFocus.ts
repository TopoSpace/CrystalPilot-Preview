import { useEffect, useRef, type RefObject } from "react";

/** Keep keyboard navigation in the active dialog and restore its opener. */
export function useDialogFocus(ref: RefObject<HTMLElement>, onClose: () => void) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const controls = () => [...root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], summary, [tabindex="0"]',
    )].filter(el => el.getClientRects().length > 0 && el.tabIndex >= 0);
    const frame = requestAnimationFrame(() => {
      if (!root.contains(document.activeElement)) (controls()[0] ?? root).focus({ preventScroll: true });
    });
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault(); event.stopPropagation(); close.current();
      }
      if (event.key !== "Tab") return;
      const items = controls();
      const first = items[0], last = items.at(-1);
      if (!first || !last) { event.preventDefault(); root.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", key);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [ref]);
}
