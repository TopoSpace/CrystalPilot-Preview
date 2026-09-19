/** Context-window ring near the model button, with a Codex-style hover card:
 * used / total / remaining of the LAST request (what the model actually
 * sees), the auto-compaction threshold, and a spinner while codex compacts. */
import { Spinner } from "../../components/ui";
import { fmtTokens } from "../../lib/format";
import { zh } from "../../lib/zh";
import { useThreadOptional } from "../../state/ThreadProvider";
import { useWorkbench } from "../../state/WorkbenchProvider";

export function ContextMeter() {
  const thread = useThreadOptional();
  const wb = useWorkbench();
  const usage = thread?.state.usage ?? null;
  const compacting = thread?.state.compacting ?? false;
  if (!usage?.total && !compacting) return null;
  const total = usage?.total ?? { input_tokens: 0, output_tokens: 0 };
  const sessionTokens = total.input_tokens + total.output_tokens;
  const engine = wb.settings?.engine;
  const window_ =
    usage?.contextWindow && usage.contextWindow > 0
      ? usage.contextWindow
      : (engine?.context_window ?? wb.settings?.model_info?.context_window ?? null);
  const cur = usage?.last ?? usage?.total ?? { input_tokens: 0, output_tokens: 0 };
  const used = cur.input_tokens + cur.output_tokens;
  const pct = window_ ? Math.min(100, (used / window_) * 100) : null;
  const tone =
    pct === null
      ? "var(--color-ink-3)"
      : pct > 90
        ? "var(--color-danger)"
        : pct > 75
          ? "var(--color-warn)"
          : "var(--color-accent)";
  const r = 6;
  const c = 2 * Math.PI * r;
  const limit = engine?.auto_compact_limit ?? wb.settings?.auto_compact_token_limit ?? null;

  return (
    <span className="group relative flex h-8 shrink-0 items-center" data-testid="context-meter">
      <span
        className="flex h-8 items-center gap-1 px-1 font-mono text-2xs text-ink-3 tabular-nums"
        aria-label={zh.ctxTipTitle}
      >
        {compacting ? (
          <Spinner className="h-3 w-3 text-ink-3" />
        ) : (
          <svg width={16} height={16} viewBox="0 0 16 16" aria-hidden="true">
            <circle cx={8} cy={8} r={r} fill="none" stroke="var(--color-raised)" strokeWidth={2.5} />
            {pct !== null && (
              <circle
                cx={8}
                cy={8}
                r={r}
                fill="none"
                stroke={tone}
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeDasharray={`${(pct / 100) * c} ${c}`}
                transform="rotate(-90 8 8)"
              />
            )}
          </svg>
        )}
        {compacting ? zh.railCompacting : pct !== null ? `${pct.toFixed(0)}%` : `${fmtTokens(sessionTokens)} tok`}
      </span>
      {/* hover card */}
      <span className="pointer-events-none absolute right-0 bottom-full z-30 mb-2 hidden w-64 rounded-card border border-line bg-bg p-3 text-left shadow-lg group-hover:block">
        <span className="block text-xs font-medium text-ink">{zh.ctxTipTitle}</span>
        {window_ ? (
          <>
            <span className="mt-1 block font-mono text-2xs text-ink-2 tabular-nums">
              {zh.ctxTipUsed} {fmtTokens(used)} / {zh.ctxTipTotal} {fmtTokens(window_)}
              {pct !== null ? `（${pct.toFixed(0)}%）` : ""}
            </span>
            <span className="block font-mono text-2xs text-ink-2 tabular-nums">
              {zh.ctxTipRemaining} {fmtTokens(Math.max(0, window_ - used))}
            </span>
          </>
        ) : (
          <span className="mt-1 block text-2xs text-ink-3">{zh.ctxTipNoWindow}</span>
        )}
        <span className="block font-mono text-2xs text-ink-3 tabular-nums">
          {zh.tokensUsed} {fmtTokens(sessionTokens)}
        </span>
        <span className="mt-1 block text-2xs leading-snug text-ink-3">
          {limit ? `${zh.ctxAutoCompact} ${fmtTokens(limit)} · ` : ""}
          {zh.ctxTipCompaction}
        </span>
      </span>
    </span>
  );
}
