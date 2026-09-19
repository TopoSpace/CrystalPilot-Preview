/** The model button's popover (Codex desktop style, 2026-09-07): provider
 * tabs, a searchable model list read from the connected API (vision /
 * context badges, catalog status), and the effort selector showing the
 * model's OWN levels as they are. Model and effort take effect on the next
 * message; a provider change reaches a running conversation through a fork
 * (codex fixes the provider per thread). */
import { clickedOutside } from "../../lib/outsideClick";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Spinner } from "../../components/ui";
import { cx, fmtTokens } from "../../lib/format";
import { forkThread, listModels } from "../../lib/wbApi";
import type { ModelEntry, ModelListResponse } from "../../lib/wbTypes";
import { formatEffort, formatModel, zh } from "../../lib/zh";
import { useWorkbench } from "../../state/WorkbenchProvider";
import { IconCheck, IconRefresh } from "../icons";
import { projectHomeUrl, threadUrl } from "../urls";

export type ModelMenuFocus = "model" | "effort";

/** "CrystalPilot Gateway (OpenAI Responses-compatible)" -> "CrystalPilot Gateway"
 * for the provider tabs; the full name stays in the tooltip. */
export function shortProviderName(name: string | undefined, pid: string): string {
  const n = (name ?? "").replace(/\s*[(（][^)）]*[)）]\s*$/, "").trim();
  return n === "" ? pid : n;
}

/** Display name for the composer button: the catalog's name, else the id. */
export function modelDisplayName(
  model: string | null | undefined,
  displayName: string | null | undefined,
): string {
  const dn = (displayName ?? "").replace(/\s*[(（][^)）]*[)）]\s*$/, "").trim();
  if (dn !== "") return dn;
  if (!model) return "";
  return model.startsWith("gpt-") ? formatModel(model) : model;
}

export function ModelMenu({
  onClose,
  focus = "model",
}: {
  onClose: () => void;
  focus?: ModelMenuFocus;
}) {
  const wb = useWorkbench();
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId: string }>();
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const s = wb.settings;
  const providerIds = useMemo(() => {
    const ids = wb.providers.map((p) => p.id);
    for (const p of s?.model_providers ?? []) if (!ids.includes(p)) ids.push(p);
    return ids;
  }, [wb.providers, s?.model_providers]);
  const effectiveProvider =
    s?.model_provider ?? wb.providers.find((p) => p.is_default)?.id ?? providerIds[0] ?? null;
  const [provider, setProvider] = useState<string | null>(effectiveProvider);
  const [query, setQuery] = useState("");
  const [list, setList] = useState<ModelListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [custom, setCustom] = useState("");

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (clickedOutside(ref.current, e)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  useEffect(() => {
    if (focus === "model") searchRef.current?.focus();
  }, [focus]);

  const load = useCallback(
    async (pid: string | null, refresh: boolean) => {
      setLoading(true);
      setListError(null);
      try {
        const res = await listModels(pid, refresh);
        setList(res);
      } catch (e) {
        setListError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [],
  );
  useEffect(() => {
    void load(provider, false);
  }, [provider, load]);

  const currentModel = s?.model ?? null;
  const currentEntry = list?.models.find((m) => m.id === currentModel) ?? null;
  const efforts =
    currentEntry?.efforts ?? s?.effort_choices ?? [];
  const effortDefault =
    currentEntry?.default_effort ?? s?.effort_default_for_model ?? s?.effort_default ?? null;
  const currentEffort = s?.effort ?? null;

  // the endpoint's own /models list is only a hint when its ids share the
  // catalog's namespace (the gateway does; a gateway that renames
  // deployments would mark everything "unlisted" - then say nothing)
  const remoteMeaningful = useMemo(
    () => (list?.models ?? []).some((m) => m.remote_available === true),
    [list],
  );
  const rows = useMemo(() => {
    const all = list?.models ?? [];
    const q = query.trim().toLowerCase();
    const visible = all.filter((m) => {
      if (q === "") return m.hidden !== true || m.id === currentModel;
      return m.id.toLowerCase().includes(q) || m.display_name.toLowerCase().includes(q);
    });
    return visible.slice(0, 300);
  }, [list, query, currentModel]);

  // the model in use is usually far down a long list: bring it into view
  // once the list renders (and only then - typing a query must not scroll)
  const listRef = useRef<HTMLDivElement>(null);
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    if (query !== "" || list === null) return;
    const key = `${provider ?? ""}:${currentModel ?? ""}`;
    if (scrolledFor.current === key) return;
    const el = listRef.current?.querySelector('[data-active="true"]');
    if (el) {
      el.scrollIntoView({ block: "nearest" });
      scrolledFor.current = key;
    }
  }, [list, query, provider, currentModel]);

  const apply = async (patch: {
    model_override?: string | null;
    effort_override?: string | null;
    model_provider_override?: string | null;
  }) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const err = await wb.changeModelEffort(patch);
    setBusy(false);
    if (err !== null) setError(err);
  };

  const pickModel = (m: ModelEntry | { id: string; efforts?: string[] }) => {
    const patch: Parameters<typeof apply>[0] = {};
    const sameAsDefault =
      m.id === s?.model_default && (provider ?? null) === (s?.model_provider_default ?? null);
    patch.model_override = sameAsDefault ? null : m.id;
    if ((provider ?? null) !== (effectiveProvider ?? null)) {
      patch.model_provider_override =
        provider === (s?.model_provider_default ?? null) ? null : provider;
    }
    // an effort override the new model cannot take is cleared (the server
    // snaps it anyway; clearing keeps the UI honest)
    const ladder = "efforts" in m && m.efforts ? m.efforts : null;
    if (s?.effort_override && ladder && !ladder.includes(s.effort_override)) {
      patch.effort_override = null;
    }
    void apply(patch);
  };

  const threadProvider =
    wb.threads.find((t) => t.thread_id === threadId)?.model_provider ??
    s?.model_provider_default ??
    null;
  const providerMismatch =
    threadId !== undefined && effectiveProvider !== null && threadProvider !== effectiveProvider;
  const project = wb.projectPath;

  const doFork = async () => {
    if (!threadId || !project || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await forkThread(threadId, project);
      void wb.refreshThreads();
      onClose();
      navigate(threadUrl(r.thread_id, project));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const restartPending = s?.engine?.restart_pending === true;

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={zh.modelMenuTitle}
      data-testid="model-menu"
      className="workbench-popover absolute right-0 bottom-full z-30 mb-2 flex w-[440px] max-w-[92vw] flex-col rounded-card border border-line bg-bg shadow-xl"
    >
      {/* providers */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-2 pt-2 pb-1.5">
        {providerIds.map((pid) => {
          const info = wb.providers.find((p) => p.id === pid);
          const active = pid === provider;
          return (
            <button
              key={pid}
              type="button"
              title={info ? `${info.name}\n${info.base_url ?? ""}` : pid}
              onClick={() => setProvider(pid)}
              className={cx(
                "h-6 shrink-0 rounded-md px-2 text-xs transition-colors",
                active ? "bg-raised text-ink" : "text-ink-2 hover:bg-raised/60 hover:text-ink",
                pid === effectiveProvider && "font-medium",
              )}
            >
              {shortProviderName(info?.name, pid)}
              {info && !info.has_key && info.auth_kind === "command" && (
                <span className="ml-1 text-2xs text-warn" title={zh.providerKeyUnset}>
                  !
                </span>
              )}
            </button>
          );
        })}
        <button
          type="button"
          title={zh.modelRefresh}
          aria-label={zh.modelRefresh}
          onClick={() => void load(provider, true)}
          className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-raised hover:text-ink"
        >
          {loading ? <Spinner className="h-3 w-3" /> : <IconRefresh size={13} />}
        </button>
      </div>

      {/* search */}
      <div className="px-2 pt-2">
        <input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={zh.modelSearch}
          aria-label={zh.modelSearch}
          className="h-8 w-full rounded-lg border border-line bg-surface px-2.5 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-accent/60"
        />
      </div>

      {/* models */}
      <div ref={listRef} className="max-h-64 overflow-y-auto px-1.5 py-1.5" data-testid="model-list">
        {listError !== null && (
          <div className="px-2 py-1 text-2xs text-danger">
            {zh.modelListError}：{listError}
          </div>
        )}
        {list?.remote && !list.remote.ok && (
          <div className="px-2 py-1 text-2xs text-warn">
            {list.remote.error ?? `HTTP ${list.remote.status ?? ""}`}
          </div>
        )}
        {rows.length === 0 && !loading && listError === null && (
          <div className="px-2 py-2 text-xs text-ink-3">{list?.note ?? zh.slashNoMatch}</div>
        )}
        {rows.map((m) => {
          const active = m.id === currentModel && provider === effectiveProvider;
          const vision = m.input_modalities.includes("image");
          const isDefault = m.id === s?.model_default && provider === s?.model_provider_default;
          const unlisted = remoteMeaningful && m.remote_available === false;
          return (
            <button
              key={m.id}
              type="button"
              data-active={active ? "true" : undefined}
              disabled={busy}
              onClick={() => pickModel(m)}
              title={unlisted ? `${m.id} · ${zh.modelUnlisted}` : (m.description ?? m.id)}
              className={cx(
                "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-raised disabled:opacity-60",
                active && "bg-raised/60",
                unlisted && "opacity-60",
              )}
            >
              <span className="flex w-4 shrink-0 justify-center">
                {active && <IconCheck size={13} className="text-ink" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-ink">
                  {m.display_name}
                  {isDefault && (
                    <span className="ml-1.5 text-2xs text-ink-3">{zh.modelDefaultTag}</span>
                  )}
                </span>
                {m.display_name !== m.id && (
                  <span className="block truncate font-mono text-2xs text-ink-3">{m.id}</span>
                )}
              </span>
              <span
                className="shrink-0 font-mono text-2xs text-ink-3 tabular-nums"
                title={zh.modelContextShort}
              >
                {m.context_window ? fmtTokens(m.context_window) : ""}
              </span>
              {/* a mark only when there is something to say */}
              {vision && (
                <span
                  className="shrink-0 rounded-md border border-accent/30 px-1 text-2xs text-accent"
                  title={zh.modelVision}
                >
                  {zh.modelVision}
                </span>
              )}
              {!m.in_catalog && (
                <span
                  className="shrink-0 rounded-md border border-line px-1 text-2xs text-ink-3"
                  title={zh.modelNotInCatalog}
                >
                  {zh.modelNewTag}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* custom id */}
      <form
        className="flex items-center gap-1.5 border-t border-line px-3 py-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          const id = custom.trim();
          if (id === "") return;
          pickModel({ id });
          setCustom("");
        }}
      >
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder={zh.modelCustomId}
          aria-label={zh.modelCustomId}
          spellCheck={false}
          className="h-6 min-w-0 flex-1 bg-transparent px-1 font-mono text-2xs text-ink outline-none placeholder:text-ink-3"
        />
        {custom.trim() !== "" && (
          <button
            type="submit"
            disabled={busy}
            className="h-6 shrink-0 rounded-md border border-line px-2 text-2xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
          >
            {zh.modelUseId}
          </button>
        )}
      </form>

      {/* effort: the model's own rungs, as they are */}
      <div className="border-t border-line px-3 py-2" data-testid="effort-picker">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-ink-2">{zh.modelEffortLabel}</span>
          <span className="font-mono text-2xs text-ink-3">
            {modelDisplayName(currentModel, currentEntry?.display_name ?? s?.model_info?.display_name)}
            {currentEffort ? ` · ${formatEffort(currentEffort)}` : ""}
          </span>
        </div>
        {efforts.length === 0 ? (
          <div className="pt-1 text-2xs text-ink-3">{zh.modelNoEffort}</div>
        ) : (
          <div className="mt-1.5 flex flex-wrap gap-1" role="radiogroup" aria-label={zh.modelEffortLabel}>
            <button
              type="button"
              role="radio"
              aria-checked={s?.effort_override == null}
              disabled={busy}
              onClick={() => void apply({ effort_override: null })}
              className={cx(
                "h-7 rounded-md border px-2 text-xs transition-colors",
                s?.effort_override == null
                  ? "border-accent/40 bg-accent/10 text-ink"
                  : "border-line text-ink-2 hover:bg-raised hover:text-ink",
              )}
              title={effortDefault ?? ""}
            >
              {zh.modelDefaultTag}
              {effortDefault ? `（${formatEffort(effortDefault)}）` : ""}
            </button>
            {efforts.map((e) => {
              const chosen = s?.effort_override === e;
              const effective = currentEffort === e;
              return (
                <button
                  key={e}
                  type="button"
                  role="radio"
                  aria-checked={chosen}
                  disabled={busy}
                  onClick={() => void apply({ effort_override: e })}
                  title={e}
                  className={cx(
                    "flex h-7 items-center gap-1 rounded-md border px-2 text-xs transition-colors",
                    chosen
                      ? "border-accent/40 bg-accent/10 text-ink"
                      : effective
                        ? "border-line bg-raised/60 text-ink"
                        : "border-line text-ink-2 hover:bg-raised hover:text-ink",
                  )}
                >
                  {formatEffort(e)}
                  <span className="font-mono text-2xs text-ink-3">{e}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* footer notes */}
      <div className="flex flex-col gap-1 border-t border-line px-3 py-2 text-2xs leading-snug text-ink-3">
        <span>{zh.modelNextTurn}</span>
        {providerMismatch && (
          <span className="text-warn">
            {zh.modelProviderNote}
            {project && (
              <>
                {" · "}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void doFork()}
                  className="underline underline-offset-2 hover:text-ink"
                >
                  {zh.modelForkAction}
                </button>
                {" · "}
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    navigate(projectHomeUrl(project));
                  }}
                  className="underline underline-offset-2 hover:text-ink"
                >
                  {zh.modelNewThreadAction}
                </button>
              </>
            )}
          </span>
        )}
        {restartPending && <span className="text-warn">{zh.modelRestartPending}</span>}
        {error !== null && <span className="text-danger">{error}</span>}
      </div>
    </div>
  );
}
