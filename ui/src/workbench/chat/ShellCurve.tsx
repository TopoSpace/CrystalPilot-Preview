/** Resolution-shell curves: the plot a crystallographer actually reads
 * before choosing a cutoff.
 *
 * estimate_resolution returns a 12-shell table (CC1/2, I/sigma,
 * completeness, Rmeas per shell); as chips and JSON it was a wall of
 * numbers, and the shape - where CC1/2 rolls off, whether completeness
 * collapses before it - is the whole point. Rendered inline in the tool
 * card so the picture sits where the decision is made.
 *
 * No cutoff line is drawn: what counts as "far enough" depends on the
 * crystal and the question, and painting a threshold onto the plot would
 * be answering that for the reader. */

export interface Shell {
  d_min?: number;
  d_max?: number;
  cc_one_half?: number;
  i_over_sigma?: number;
  completeness?: number;
  r_meas?: number;
}

// axis labels are text-2xs (11 px floor, index.css): the gutters hold them
const W = 260;
const H = 96;
const PAD_L = 30;
const PAD_R = 6;
const PAD_T = 8;
const PAD_B = 18;

interface Series {
  key: keyof Shell;
  label: string;
  color: string;
  /** map raw -> 0..1 for the shared axis */
  norm: (v: number, max: number) => number;
}

/** CC1/2 and completeness are already 0-1 (or 0-100); I/sigma is not, so
 * it rides its own scale and is labelled with its own max. */
const SERIES: Series[] = [
  {
    key: "cc_one_half",
    label: "CC½",
    color: "var(--color-accent)",
    norm: (v) => (v > 1 ? v / 100 : v),
  },
  {
    key: "completeness",
    label: "完整度",
    color: "var(--color-ok)",
    norm: (v) => (v > 1 ? v / 100 : v),
  },
  {
    key: "i_over_sigma",
    label: "I/σ",
    color: "var(--color-warn)",
    norm: (v, max) => (max > 0 ? v / max : 0),
  },
];

export interface PlotLine {
  key: string;
  label: string;
  color: string;
  pts: string;
}

export interface ShellPlot {
  lines: PlotLine[];
  isoMax: number;
  dLo: number;
  dHi: number;
  py: (t: number) => number;
}

/** Pure geometry, exported so the axes can be tested: x is 1/d^2 (the
 * linear scale resolution shells are actually cut on) increasing to the
 * right = LOW resolution on the left, and y is inverted for SVG so 1.0
 * sits at the top. Both are easy to get backwards and neither shows up
 * as an error - only as a plot that quietly says the opposite thing. */
export function shellPlot(shells: Shell[]): ShellPlot | null {
  const rows = shells.filter((s) => typeof s.d_min === "number");
  if (rows.length < 3) return null;
  const xs = rows.map((s) => 1 / ((s.d_min as number) * (s.d_min as number)));
  const xMin = Math.min(...xs);
  const xSpan = Math.max(...xs) - xMin || 1;
  const px = (x: number) => PAD_L + ((x - xMin) / xSpan) * (W - PAD_L - PAD_R);
  const py = (t: number) => PAD_T + (1 - t) * (H - PAD_T - PAD_B);
  const isoMax = Math.max(
    ...rows.map((s) =>
      typeof s.i_over_sigma === "number" ? s.i_over_sigma : 0,
    ),
    0,
  );
  const lines = SERIES.map((s) => {
    const pts = rows
      .map((row, i) => {
        const v = row[s.key];
        return typeof v === "number"
          ? `${px(xs[i]).toFixed(1)},${py(s.norm(v, isoMax)).toFixed(1)}`
          : null;
      })
      .filter((p): p is string => p !== null);
    return { key: s.key as string, label: s.label, color: s.color,
             pts: pts.join(" ") };
  }).filter((s) => s.pts.split(" ").length >= 3);
  if (lines.length === 0) return null;
  return {
    lines,
    isoMax,
    dLo: rows[0].d_min as number,
    dHi: rows[rows.length - 1].d_min as number,
    py,
  };
}

export function ShellCurve({ shells }: { shells: Shell[] }) {
  const plot = shellPlot(shells);
  if (plot === null) return null;
  const { lines, isoMax, dLo, dHi, py } = plot;

  return (
    <div>
      <svg
        width={W}
        height={H}
        role="img"
        aria-label={`分辨率壳层曲线，${dLo.toFixed(2)} 到 ${dHi.toFixed(2)} Å`}
      >
        {[0, 0.5, 1].map((t) => (
          <line
            key={t}
            x1={PAD_L}
            x2={W - PAD_R}
            y1={py(t)}
            y2={py(t)}
            stroke="var(--color-line)"
            strokeWidth={1}
          />
        ))}
        {[0, 0.5, 1].map((t) => (
          <text
            key={t}
            x={PAD_L - 4}
            y={py(t) + 3}
            textAnchor="end"
            className="fill-[var(--color-ink-3)] text-2xs"
          >
            {t === 1 ? "1" : t === 0 ? "0" : ".5"}
          </text>
        ))}
        {lines.map((s) => (
          <polyline
            key={s.key}
            points={s.pts}
            fill="none"
            stroke={s.color}
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
        <text
          x={PAD_L}
          y={H - 4}
          className="fill-[var(--color-ink-3)] text-2xs"
        >
          {dLo.toFixed(2)} Å
        </text>
        <text
          x={W - PAD_R}
          y={H - 4}
          textAnchor="end"
          className="fill-[var(--color-ink-3)] text-2xs"
        >
          {dHi.toFixed(2)} Å
        </text>
      </svg>
      <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-2xs">
        {lines.map((s) => (
          <span key={s.key} className="flex items-center gap-1">
            <span
              className="inline-block h-[2px] w-3 rounded"
              style={{ background: s.color }}
              aria-hidden
            />
            <span className="text-ink-3">
              {s.label}
              {s.key === "i_over_sigma" && isoMax > 0
                ? `（满刻度 ${isoMax.toFixed(0)}）`
                : ""}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
