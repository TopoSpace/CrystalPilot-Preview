/** How much of the crystal is drawn, in one phrase.
 *
 * Lives apart from the pane because two places need the same words: the
 * toolbar's caption for a frame handed to the agent, and the header card's
 * status line. If they drifted, a frame quote would claim one extent while
 * the panel above it showed another.
 */
import { t } from "../../lib/i18n";
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
      ? `${t.modeSuper} ${s.superN}×${s.superN}×${s.superN}`
      : s.mode === "radius"
        ? `${t.modeRadius} ${s.packRadius ?? 8} Å${s.packCenter ? ` · ${s.packCenter}` : ""}`
        : s.mode === "range"
          ? `${t.modeRange} ${rangeLabel(s.packRange ?? { lo: [-0.5, -0.5, -0.5], hi: [1.5, 1.5, 1.5] })}`
          : s.mode === "cell"
            ? t.modeCell
            : t.modeAsu;
  const extra: string[] = [];
  if (s.growLevel > 0) extra.push(`${t.modeGrow} ${t.crystal.extGrowLayers(s.growLevel)}`);
  if (s.growAll) extra.push(t.growAll);
  if (s.complete) extra.push(t.growComplete);
  if (s.grown.length > 0) extra.push(t.crystal.extManual(s.grown.length));
  return extra.length > 0 ? t.crystal.extWithExtras(slice, extra) : slice;
}
