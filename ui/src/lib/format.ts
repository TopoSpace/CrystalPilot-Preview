/** Formatting + narrowing helpers used across the UI. */

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function asNum(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

export function asStr(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

/** Fixed-point format; em dash when the value is missing. */
export function fmtFixed(v: unknown, digits: number): string {
  const n = asNum(v);
  return n === undefined ? "—" : n.toFixed(digits);
}

export function fmtInt(v: unknown): string {
  const n = asNum(v);
  return n === undefined ? "—" : Math.round(n).toLocaleString("en-US");
}

export function fmtSeconds(v: unknown): string {
  const n = asNum(v);
  if (n === undefined) return "";
  if (n < 0.05) return "<0.1 s";
  if (n < 10) return `${n.toFixed(1)} s`;
  if (n < 90) return `${Math.round(n)} s`;
  return `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
}

/** "a b c A - al be ga deg" from a 6-component cell. */
export function fmtCell(cell: number[] | undefined): string | undefined {
  if (!cell || cell.length !== 6) return undefined;
  const [a, b, c, al, be, ga] = cell;
  const lengths = [a, b, c].map((v) => v.toFixed(2)).join(" ");
  const angles = [al, be, ga].map((v) => v.toFixed(0)).join(" ");
  return `${lengths} Å · ${angles}°`;
}

export function timeAgo(epochSeconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (s < 60) return "just now";
  const m = s / 60;
  if (m < 60) return `${Math.floor(m)}m ago`;
  const h = m / 60;
  if (h < 24) return `${Math.floor(h)}h ago`;
  const d = h / 24;
  if (d < 7) return `${Math.floor(d)}d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

/** Compact token count: 842 / 87.3K / 1.24M. */
export function fmtTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1000_000).toFixed(2)}M`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** 00:00-style elapsed time from milliseconds ("" when unknown). */
export function fmtMmSs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return "";
  const total = Math.max(0, Math.round(ms / 1000));
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
