/** Slim invisible drag strip straddling a panel border; shows an accent line
 * on hover/drag. Keyboard users can resize with arrow keys (8 px steps). */
import { cx } from "../lib/format";
import { zh } from "../lib/zh";
import type { ResizableEdge } from "./useResizable";

export function ResizeHandle({
  edge,
  resizable,
}: {
  /** which edge of the panel this handle sits on */
  edge: "left" | "right";
  resizable: ResizableEdge;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={zh.resizeHandle}
      tabIndex={-1}
      {...resizable.handleProps}
      className={cx(
        "absolute inset-y-0 z-20 w-[7px] cursor-col-resize touch-none",
        edge === "right" ? "-right-[4px]" : "-left-[4px]",
      )}
    >
      <div
        className={cx(
          "mx-auto h-full w-[3px] rounded-pill transition-colors",
          resizable.dragging
            ? "bg-accent/70"
            : "bg-transparent hover:bg-accent/40",
        )}
      />
    </div>
  );
}
