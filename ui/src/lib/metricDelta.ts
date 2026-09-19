export interface MetricDelta {
  changed: boolean;
  improved: boolean;
  worsened: boolean;
  direction: "up" | "down" | null;
}

/** Colour/arrows require an explicit comparable verdict. GooF measures distance to 1. */
export function metricDelta(
  cur: number | null | undefined,
  prev: number | null | undefined,
  digits: number,
  ideal?: number,
  stale = false,
  comparable = false,
): MetricDelta {
  const quiet: MetricDelta = { changed: false, improved: false, worsened: false, direction: null };
  if (stale || cur == null || prev == null || !Number.isFinite(cur) || !Number.isFinite(prev)) {
    return quiet;
  }
  if (Math.abs(cur - prev) < 0.5 / 10 ** digits) return quiet;
  const change = ideal === undefined ? cur - prev : Math.abs(cur - ideal) - Math.abs(prev - ideal);
  const epsilon = Number.EPSILON * Math.max(1, Math.abs(cur), Math.abs(prev)) * 8;
  return {
    changed: true,
    improved: comparable && change < -epsilon,
    worsened: comparable && change > epsilon,
    direction: comparable ? (cur > prev ? "up" : "down") : null,
  };
}
