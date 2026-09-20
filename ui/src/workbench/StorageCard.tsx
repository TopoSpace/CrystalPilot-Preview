/** "项目占用" on the project home: what the project directory holds (the
 * user's own files, deliverables, system-generated data) and what a
 * cleanup would reclaim. The cleanup is a dry run first - the list is shown
 * - and only removes unreferenced intermediates (see
 * crystalpilot/refine/storage.py); user files, node snapshots, reflection
 * revisions and CrystalPilot Results are never touched. */
import { useCallback, useEffect, useState } from "react";
import { ApiError, projectCleanup, projectUsage } from "../lib/wbApi";
import type { CleanupPlanResponse, ProjectUsage } from "../lib/wbTypes";
import { t } from "../lib/i18n";

export function fmtBytes(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

const KIND_ZH: Record<string, string> = {
  link: t.storageKindLink,
  strip: t.storageKindStrip,
  delete: t.storageKindDelete,
  rmdir: t.storageKindRmdir,
};

export function StorageCard({ project }: { project: string }) {
  const [usage, setUsage] = useState<ProjectUsage | null>(null);
  const [plan, setPlan] = useState<CleanupPlanResponse | null>(null);
  const [busy, setBusy] = useState<"usage" | "plan" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy("usage");
    setError(null);
    try {
      setUsage(await projectUsage(project));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [project]);

  useEffect(() => {
    setUsage(null);
    setPlan(null);
    setDone(null);
    void load();
  }, [load]);

  const preview = async () => {
    setBusy("plan");
    setError(null);
    setDone(null);
    try {
      setPlan(await projectCleanup(project, false));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setBusy("apply");
    setError(null);
    try {
      const r = await projectCleanup(project, true);
      const freed = r.result?.freed_bytes ?? 0;
      const skipped = r.result?.n_skipped ?? 0;
      setDone(`${t.storageFreed} ${fmtBytes(freed)}${skipped > 0 ? ` · ${skipped} ${t.storageSkipped}` : ""}`);
      setPlan(null);
      if (r.usage) setUsage(r.usage);
      else void load();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? t.storageBusy : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (usage === null && error === null) return null;

  return (
    <section
      data-testid="storage-card"
      className="mx-auto mt-6 w-full max-w-2xl rounded-card border border-line bg-surface/60 px-4 py-3 text-left text-xs text-ink-2"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-ink">{t.storageTitle}</span>
        {usage && (
          <span className="font-mono tabular-nums text-ink-2" data-testid="storage-total">
            {fmtBytes(usage.unique_bytes)}
          </span>
        )}
      </div>
      {usage && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
          <Stat label={t.storageUser} value={fmtBytes(usage.user_bytes)} />
          <Stat label={t.storageResults} value={fmtBytes(usage.results_bytes)} />
          <Stat label={t.storageSystem} value={fmtBytes(usage.system_bytes)} />
          <Stat
            label={t.storageReclaimable}
            value={fmtBytes(usage.reclaimable_bytes)}
            testId="storage-reclaimable"
            strong={usage.reclaimable_bytes > 0}
          />
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {plan === null ? (
          <button
            type="button"
            onClick={() => void preview()}
            disabled={busy !== null || (usage !== null && usage.n_actions === 0)}
            data-testid="storage-preview"
            className="h-7 rounded-pill border border-line px-3 text-xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            {busy === "plan" ? t.loading : usage !== null && usage.n_actions === 0 ? t.storageNothing : t.storagePreview}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void apply()}
              disabled={busy !== null || plan.n_actions === 0}
              data-testid="storage-apply"
              className="h-7 rounded-pill bg-accent px-3 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy === "apply" ? t.loading : `${t.storageApply}${t.paren(fmtBytes(plan.reclaimable_bytes))}`}
            </button>
            <button
              type="button"
              onClick={() => setPlan(null)}
              className="h-7 rounded-pill border border-line px-3 text-xs text-ink-2 hover:bg-raised"
            >
              {t.cancel}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => void load()}
          disabled={busy !== null}
          className="h-7 rounded-pill px-2 text-xs text-ink-3 hover:text-ink"
        >
          {t.statusRefresh}
        </button>
        {done && <span className="text-ok">{done}</span>}
        {error && <span className="text-warn">{error}</span>}
      </div>
      {plan !== null && (
        <div className="mt-2.5 rounded-lg bg-raised/40 p-2.5" data-testid="storage-plan">
          <div className="text-2xs text-ink-3">{t.storagePlanHint}</div>
          <ul className="mt-1 flex flex-col gap-0.5">
            {Object.entries(plan.by_kind).map(([kind, v]) => (
              <li key={kind} className="flex justify-between font-mono text-2xs tabular-nums">
                <span>{KIND_ZH[kind] ?? kind} × {v.count}</span>
                <span>{fmtBytes(v.bytes)}</span>
              </li>
            ))}
          </ul>
          <details className="mt-1.5">
            <summary className="cursor-pointer list-none text-2xs text-ink-3 select-none hover:text-ink-2">
              {t.storagePlanList}{t.paren(plan.actions.length)}
            </summary>
            <div className="mt-1 max-h-48 overflow-y-auto font-mono text-2xs leading-relaxed text-ink-3">
              {plan.actions.map((a, i) => (
                <div key={i} className="break-all">
                  {KIND_ZH[a.kind] ?? a.kind} · {a.path} · {fmtBytes(a.bytes)} · {a.reason}
                </div>
              ))}
            </div>
          </details>
          {plan.notes.length > 0 && (
            <div className="mt-1 text-2xs text-ink-3">{plan.notes.join(t.sepClause)}</div>
          )}
        </div>
      )}
      <div className="mt-2 text-2xs text-ink-3">{t.storageRules}</div>
    </section>
  );
}

function Stat({ label, value, testId, strong }: { label: string; value: string; testId?: string; strong?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="text-2xs text-ink-3">{label}</span>
      <span className={strong ? "font-mono tabular-nums text-ink" : "font-mono tabular-nums text-ink-2"} data-testid={testId}>
        {value}
      </span>
    </div>
  );
}
