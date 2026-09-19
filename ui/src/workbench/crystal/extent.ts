/** How much of the crystal is drawn, in one phrase.
 *
 * Lives apart from the pane because two places need the same words: the
 * toolbar's caption for a frame handed to the agent, and the header card's
 * status line. If they drifted, a frame quote would claim one extent while
 * the panel above it showed another.
 */
import { zh } from "../../lib/zh";
import type { CrystalMode, PackRange } from "../../state/crystalReducer";

function fmtFrac(v: number): string {
  return (Math.round(v * 100) / 100).toString().replace("-", "−");
}

/** "−0.5…1.5" when the box is the same on every axis, else per axis. */
export function rangeLabel(r: PackRange): string {
  const same = r.lo.every((v) => v === r.lo[0]) && r.hi.every((v) => v === r.hi[0]);
  if (same) return `${fmtFrac(r.lo[0])}…${fmtFrac(r.hi[0])}`;
  return ["a", "b", "c"].map((ax, k) => `${ax} ${fmtFrac(r.lo[k])}…${fmtFrac(r.hi[k])}`).join(" ");
}

export function extentLabel(s: {
  mode: CrystalMode;
  growLevel: number;
  superN: number;
  grown: unknown[];
  packRadius?: number;
  packCenter?: string | null;
  packRange?: PackRange;
  complete?: boolean;
  growAll?: boolean;
}): string {
  const slice =
    s.mode === "super"
      ? `${zh.modeSuper} ${s.superN}×${s.superN}×${s.superN}`
      : s.mode === "radius"
        ? `${zh.modeRadius} ${s.packRadius ?? 8} Å${s.packCenter ? ` · ${s.packCenter}` : ""}`
        : s.mode === "range"
          ? `${zh.modeRange} ${rangeLabel(s.packRange ?? { lo: [-0.5, -0.5, -0.5], hi: [1.5, 1.5, 1.5] })}`
          : s.mode === "cell"
            ? zh.modeCell
            : zh.modeAsu;
  const extra: string[] = [];
  if (s.growLevel > 0) extra.push(`${zh.modeGrow} ${s.growLevel} 层`);
  if (s.growAll) extra.push(zh.growAll);
  if (s.complete) extra.push(zh.growComplete);
  if (s.grown.length > 0) extra.push(`手工 ${s.grown.length} 处`);
  return extra.length > 0 ? `${slice}（${extra.join("，")}）` : slice;
}
