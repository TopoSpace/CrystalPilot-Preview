/** Browser-side diagnostics (round-3 R1).
 *
 * The 2026-09-05 forensic replay could not name the cause of a historical
 * blank page because nothing recorded the exception, its component stack or
 * where the transcript stood at that moment. This module keeps a tiny
 * context (thread, cursor, node, view) that the app updates as it goes,
 * and ships every uncaught error / boundary catch to the server as one JSON
 * line. Reporting is best-effort: a failed POST must never throw.
 */

export interface DiagnosticContext {
  threadId?: string | null;
  project?: string | null;
  cursor?: number;
  lastEventKind?: string | null;
  node?: string | null;
  view?: string | null;
  itemCount?: number;
}

export interface DiagnosticReport {
  area: string;
  message: string;
  stack?: string | null;
  componentStack?: string | null;
  context: DiagnosticContext;
  ts: number;
  url: string;
  build?: string | null;
}

const ctx: DiagnosticContext = {};
const recent: DiagnosticReport[] = [];
const MAX_RECENT = 20;
let installed = false;
// burst guard: a render loop can throw hundreds of times per second
let windowStart = 0;
let windowCount = 0;
const BURST_WINDOW_MS = 10_000;
const BURST_MAX = 8;

export function setDiagnosticContext(patch: DiagnosticContext): void {
  Object.assign(ctx, patch);
}

export function diagnosticContext(): DiagnosticContext {
  return { ...ctx };
}

export function recentDiagnostics(): DiagnosticReport[] {
  return recent.slice();
}

function allowed(): boolean {
  const now = Date.now();
  if (now - windowStart > BURST_WINDOW_MS) {
    windowStart = now;
    windowCount = 0;
  }
  windowCount += 1;
  return windowCount <= BURST_MAX;
}

export function reportUiDiagnostic(
  area: string,
  error: unknown,
  componentStack?: string | null,
): DiagnosticReport {
  const err = error instanceof Error ? error : null;
  const report: DiagnosticReport = {
    area,
    message: err ? `${err.name}: ${err.message}` : String(error),
    stack: err?.stack ?? null,
    componentStack: componentStack ?? null,
    context: diagnosticContext(),
    ts: Date.now() / 1000,
    url: typeof location !== "undefined" ? location.href : "",
  };
  recent.push(report);
  if (recent.length > MAX_RECENT) recent.splice(0, recent.length - MAX_RECENT);
  if (allowed() && typeof fetch === "function") {
    try {
      void fetch("/api/ui/diagnostics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(report),
        keepalive: true,
      }).catch(() => undefined);
    } catch {
      // never let diagnostics take the app down
    }
  }
  return report;
}

/** Text a user can paste into a bug report. */
export function formatDiagnostic(r: DiagnosticReport): string {
  const lines = [
    `[${new Date(r.ts * 1000).toISOString()}] ${r.area}: ${r.message}`,
    `url: ${r.url}`,
    `context: ${JSON.stringify(r.context)}`,
  ];
  if (r.stack) lines.push("stack:", r.stack);
  if (r.componentStack) lines.push("components:", r.componentStack.trim());
  return lines.join("\n");
}

/** window.onerror / unhandledrejection -> report. Idempotent. */
export function installGlobalErrorHandlers(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (e) => {
    reportUiDiagnostic("window.error", e.error ?? e.message);
  });
  window.addEventListener("unhandledrejection", (e) => {
    reportUiDiagnostic("unhandledrejection", e.reason);
  });
}
