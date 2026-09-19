import { useLayoutEffect, useRef, type ComponentProps } from "react";
import { useViewMode } from "../../state/ViewMode";
import { keepFocusOnSummary } from "./detailsFocus";

/** A view-mode change must not close a fold while its contents have focus. */
export function ProcessDetails({ running, ...props }: Omit<ComponentProps<"details">, "open" | "onToggle"> & { running?: boolean }) {
  const { verbose } = useViewMode();
  const ref = useRef<HTMLDetailsElement>(null);
  useLayoutEffect(() => {
    const details = ref.current;
    if (!details) return;
    if (verbose || !details.contains(document.activeElement)) details.open = verbose;
  }, [verbose]);
  const wasRunning = useRef(running);
  useLayoutEffect(() => {
    const details = ref.current;
    if (details && wasRunning.current && !running && !verbose && !details.contains(document.activeElement)) details.open = false;
    wasRunning.current = running;
  }, [running, verbose]);
  return <details {...props} ref={ref} onToggle={(event) => keepFocusOnSummary(event.currentTarget)} />;
}
