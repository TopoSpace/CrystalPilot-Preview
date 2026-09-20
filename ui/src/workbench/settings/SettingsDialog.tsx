/** 设置 (2026-09-07): one dialog for everything that used to need the
 * backend or the CLI - providers & keys, the config.toml defaults (model /
 * effort / provider), context-window and auto-compaction limits (global and
 * per project), appearance, the kernel (version, source, update hint,
 * catalog), and about. Opened from the sidebar gear, the "更多设置…" link
 * and /settings. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertBanner, Segmented, Spinner } from "../../components/ui";
import { cx, fmtTokens } from "../../lib/format";
import {
  FONT_SIZES,
  useTheme,
  type FontSize,
  type Palette,
  type ThemePreference,
} from "../../lib/theme";
import {
  compactThread,
  getGlobalConfig,
  health,
  listModels,
  restartEngine,
  setGlobalConfig,
} from "../../lib/wbApi";
import type { GlobalConfig, ModelEntry, UiBuildInfo } from "../../lib/wbTypes";
import { LANGUAGES, LANGUAGE_NAMES, formatEffort, language, setLanguage, t } from "../../lib/i18n";
import { rememberSettingsSection } from "../../lib/settingsReopen";
import { useThreadOptional } from "../../state/ThreadProvider";
import { useWorkbench, type SettingsSection } from "../../state/WorkbenchProvider";
import { Switch } from "../composer/Switch";
import { IconX, IconTool, IconSpark, IconFile, IconSun, IconSettings, IconCrystal } from "../icons";
import { useDialogFocus } from "../useDialogFocus";
import { ProvidersSection } from "./ProvidersSection";

const SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "providers", label: t.secProviders },
  { id: "models", label: t.secModels },
  { id: "context", label: t.secContext },
  { id: "appearance", label: t.secAppearance },
  { id: "advanced", label: t.secAdvanced },
  { id: "about", label: t.secAbout },
];

const SECTION_ICONS = { providers: IconTool, models: IconSpark, context: IconFile, appearance: IconSun, advanced: IconSettings, about: IconCrystal };
const SECTION_DESCRIPTIONS: Record<SettingsSection, string> = {
  providers: t.secDescProviders,
  models: t.secDescModels,
  context: t.secDescContext,
  appearance: t.secDescAppearance,
  advanced: t.secDescAdvanced,
  about: t.secDescAbout,
};

const inputCls =
  "settings-input h-9 w-full rounded-lg border border-line bg-bg px-3 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-accent/60 disabled:opacity-50";
const btnCls =
  "h-8 rounded-lg border border-line px-3 text-xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40";
const primaryCls =
  "h-8 rounded-lg bg-ink px-3 text-xs font-medium text-bg transition-opacity hover:opacity-85 disabled:opacity-40";

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-2xs text-ink-3">
      <span>{label}</span>
      {children}
      {hint && <span className="leading-relaxed">{hint}</span>}
    </label>
  );
}

function parseIntOrNull(v: string): number | null {
  const t = v.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

function useGlobalConfig() {
  const [cfg, setCfg] = useState<GlobalConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setCfg(await getGlobalConfig());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return { cfg, error, reload: load };
}

// ---------------------------------------------------------------- models
function ModelsSection() {
  const wb = useWorkbench();
  const { cfg, error: loadError, reload } = useGlobalConfig();
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!cfg) return;
    setProvider(cfg.model_provider ?? "");
    setModel(cfg.model ?? "");
    setEffort(cfg.model_reasoning_effort ?? "");
  }, [cfg]);

  useEffect(() => {
    let alive = true;
    void listModels(provider || null)
      .then((r) => {
        if (alive) setModels(r.models);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [provider]);

  const entry = models.find((m) => m.id === model) ?? null;
  const ladder = entry?.efforts ?? wb.settings?.effort_choices ?? [];

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setMsg(null);
    setError(null);
    try {
      await setGlobalConfig({
        model: model.trim() || null,
        model_provider: provider || null,
        model_reasoning_effort: effort || null,
      });
      await reload();
      void wb.refreshSettings();
      setMsg(t.providerSaved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs leading-relaxed text-ink-3">{t.cfgNote}</p>
      {loadError && <AlertBanner>{loadError}</AlertBanner>}
      {error && <AlertBanner>{error}</AlertBanner>}
      <Field label={t.cfgDefaultProvider}>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} className={inputCls}>
          <option value="">openai</option>
          {wb.providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}{t.paren(p.id)}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t.cfgDefaultModel}>
        <input
          list="cp-global-models"
          value={model}
          spellCheck={false}
          onChange={(e) => setModel(e.target.value)}
          className={cx(inputCls, "font-mono")}
        />
        <datalist id="cp-global-models">
          {models.slice(0, 300).map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </datalist>
      </Field>
      <Field label={t.cfgDefaultEffort}>
        {ladder.length > 0 ? (
          <select value={effort} onChange={(e) => setEffort(e.target.value)} className={inputCls}>
            <option value="">{t.modelDefaultTag}</option>
            {ladder.map((e) => (
              <option key={e} value={e}>
                {formatEffort(e)}{t.paren(e)}
              </option>
            ))}
          </select>
        ) : (
          <input value={effort} onChange={(e) => setEffort(e.target.value)} className={cx(inputCls, "font-mono")} />
        )}
      </Field>
      <div className="flex items-center gap-2">
        <button type="button" disabled={saving || !cfg} onClick={() => void save()} className={primaryCls}>
          {saving ? t.providerSaving : t.cfgSave}
        </button>
        {msg && <span className="text-xs text-ok">{msg}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- context
function ContextSection() {
  const wb = useWorkbench();
  const thread = useThreadOptional();
  const { threadId } = useParams<{ threadId: string }>();
  const { cfg, error: loadError, reload } = useGlobalConfig();
  const [gWindow, setGWindow] = useState("");
  const [gCompact, setGCompact] = useState("");
  const [pWindow, setPWindow] = useState("");
  const [pCompact, setPCompact] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!cfg) return;
    setGWindow(cfg.model_context_window?.toString() ?? "");
    setGCompact(cfg.model_auto_compact_token_limit?.toString() ?? "");
  }, [cfg]);
  const s = wb.settings;
  useEffect(() => {
    setPWindow(s?.context_window_override?.toString() ?? "");
    setPCompact(s?.auto_compact_token_limit?.toString() ?? "");
  }, [s?.context_window_override, s?.auto_compact_token_limit]);

  const saveGlobal = async () => {
    setSaving("global");
    setMsg(null);
    setError(null);
    try {
      await setGlobalConfig({
        model_context_window: parseIntOrNull(gWindow),
        model_auto_compact_token_limit: parseIntOrNull(gCompact),
      });
      await reload();
      void wb.refreshSettings();
      setMsg(t.providerSaved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  };
  const saveProject = async () => {
    setSaving("project");
    setMsg(null);
    setError(null);
    const err = await wb.patchSettings({
      context_window_override: parseIntOrNull(pWindow),
      auto_compact_token_limit: parseIntOrNull(pCompact),
    });
    setSaving(null);
    if (err !== null) setError(err);
    else setMsg(t.providerSaved);
  };
  const compactNow = async () => {
    if (!threadId) return;
    setSaving("compact");
    setMsg(null);
    setError(null);
    try {
      await compactThread(threadId, wb.projectPath);
      setMsg(t.ctxCompactSent);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  };

  const usage = thread?.state.usage ?? null;
  const cur = usage?.last ?? usage?.total ?? null;
  const used = cur ? cur.input_tokens + cur.output_tokens : null;
  const engine = s?.engine;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs leading-relaxed text-ink-3">{t.ctxHint}</p>
      {loadError && <AlertBanner>{loadError}</AlertBanner>}
      {error && <AlertBanner>{error}</AlertBanner>}
      {msg && <div className="text-xs text-ok">{msg}</div>}

      <div className="rounded-card border border-line p-3">
        <div className="mb-2 text-sm font-medium text-ink">{t.ctxGlobal}</div>
        <div className="grid grid-cols-2 gap-2.5">
          <Field label={t.ctxWindow}>
            <input value={gWindow} inputMode="numeric" onChange={(e) => setGWindow(e.target.value)} className={cx(inputCls, "font-mono")} />
          </Field>
          <Field label={t.ctxAutoCompact}>
            <input value={gCompact} inputMode="numeric" onChange={(e) => setGCompact(e.target.value)} className={cx(inputCls, "font-mono")} />
          </Field>
        </div>
        <button type="button" disabled={saving !== null || !cfg} onClick={() => void saveGlobal()} className={cx(primaryCls, "mt-2.5")}>
          {saving === "global" ? t.providerSaving : t.providerSave}
        </button>
      </div>

      <div className="rounded-card border border-line p-3">
        <div className="mb-2 text-sm font-medium text-ink">{t.ctxProject}</div>
        {!wb.projectPath ? (
          <div className="text-xs text-ink-3">{t.settingsNoProject}</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2.5">
              <Field label={t.ctxWindow}>
                <input value={pWindow} inputMode="numeric" onChange={(e) => setPWindow(e.target.value)} className={cx(inputCls, "font-mono")} />
              </Field>
              <Field label={t.ctxAutoCompact}>
                <input value={pCompact} inputMode="numeric" onChange={(e) => setPCompact(e.target.value)} className={cx(inputCls, "font-mono")} />
              </Field>
            </div>
            <div className="mt-2 text-2xs text-ink-3">
              {t.ctxEngineNow}{t.colon}{t.ctxWindowShort}{" "}
              <span className="font-mono tabular-nums">
                {engine?.context_window ? fmtTokens(engine.context_window) : "—"}
              </span>
              {" · "}
              {t.ctxCompactShort}{" "}
              <span className="font-mono tabular-nums">
                {engine?.auto_compact_limit ? fmtTokens(engine.auto_compact_limit) : "—"}
              </span>
              {engine?.restart_pending ? <span className="text-warn"> · {t.modelRestartPending}</span> : null}
            </div>
            <div className="mt-2.5 flex items-center gap-2">
              <button type="button" disabled={saving !== null} onClick={() => void saveProject()} className={primaryCls}>
                {saving === "project" ? t.providerSaving : t.providerSave}
              </button>
              <button
                type="button"
                disabled={saving !== null || !threadId}
                title={threadId ? "" : t.noteNeedThread}
                onClick={() => void compactNow()}
                className={btnCls}
              >
                {saving === "compact" ? <Spinner className="h-3 w-3" /> : t.ctxCompactNow}
              </button>
            </div>
          </>
        )}
      </div>

      {usage && (
        <div className="rounded-card border border-line p-3">
          <div className="mb-1 text-sm font-medium text-ink">{t.ctxCurrentUsage}</div>
          <div className="font-mono text-2xs text-ink-2 tabular-nums">
            {used !== null ? `${t.ctxTipUsed} ${fmtTokens(used)}` : ""}
            {usage.contextWindow ? ` / ${t.ctxTipTotal} ${fmtTokens(usage.contextWindow)}` : ""}
            {usage.total ? ` · ${t.tokensUsed} ${fmtTokens(usage.total.input_tokens + usage.total.output_tokens)}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- appearance
const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: t.themeSystem },
  { value: "light", label: t.themeLight },
  { value: "dark", label: t.themeDark },
];

const PALETTE_OPTIONS: {
  value: Palette;
  label: string;
  swatches: readonly [string, string, string];
}[] = [
  { value: "anthropic", label: "Anthropic", swatches: ["#faf9f5", "#a84b28", "#504b44"] },
  { value: "openai", label: "OpenAI", swatches: ["#f7f8f7", "#066b49", "#3f5047"] },
  { value: "kimi", label: "Kimi", swatches: ["#f8f9fc", "#4556b9", "#535b72"] },
];

function AppearanceSection() {
  const { preference, setPreference, palette, setPalette, fontSize, setFontSize,
    presentation, setPresentation, presentationName, setPresentationName } = useTheme();
  return (
    <div className="flex flex-col gap-5" data-testid="appearance-settings">
      <div className="flex flex-col gap-1.5" data-testid="language-settings">
        <span className="text-xs font-medium text-ink-2">{t.language}</span>
        <Segmented
          options={LANGUAGES.map((code) => ({ value: code, label: LANGUAGE_NAMES[code] }))}
          value={language}
          onChange={(next) => {
            if (next === language) return;
            rememberSettingsSection("appearance");
            setLanguage(next);
          }}
        />
        <p className="text-2xs leading-relaxed text-ink-3">{t.languageHint}</p>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-xs font-medium text-ink-2">{t.appPalette}</span>
          <span className="text-2xs text-ink-3">{t.appPaletteNote}</span>
        </div>
        <div className="grid grid-cols-3 gap-2" aria-label={t.appPalette} role="group">
          {PALETTE_OPTIONS.map((option) => {
            const active = palette === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                data-testid={`palette-${option.value}`}
                onClick={() => setPalette(option.value)}
                className={cx(
                  "min-w-0 rounded-card border p-2.5 text-left transition-colors duration-150",
                  active
                    ? "border-accent bg-raised text-ink"
                    : "border-line bg-surface text-ink-2 hover:border-accent/50 hover:bg-raised/70",
                )}
              >
                <span className="mb-2 flex items-center gap-1" aria-hidden="true">
                  {option.swatches.map((color) => (
                    <span
                      key={color}
                      className="h-3.5 min-w-0 flex-1 rounded-sm border border-black/10"
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </span>
                <span className="block truncate text-xs font-medium">{option.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-ink-2">{t.appTheme}</span>
        <Segmented options={THEME_OPTIONS} value={preference} onChange={setPreference} />
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-ink-2">{t.fontSize}</span>
        <Segmented
          options={FONT_SIZES.map((n) => ({
            value: String(n),
            label: t.fontSizeNames[n] ?? String(n),
            title: `${n} px`,
          }))}
          value={String(fontSize)}
          onChange={(v) => setFontSize(Number(v) as FontSize)}
        />
      </div>
      <div className="flex flex-col gap-3 border-t border-line pt-4" data-testid="presentation-settings">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-ink-2">{t.appPresentation}</span>
          <Switch label={t.appPresentation} checked={presentation} onToggle={() => setPresentation(!presentation)} />
        </div>
        <Field label={t.appBrandName} hint={t.appBrandNameHint}>
          <input aria-label={t.appBrandName} value={presentationName} onChange={e => setPresentationName(e.target.value)} disabled={!presentation}
            maxLength={48} placeholder={t.appBrandNamePlaceholder} className={inputCls} />
        </Field>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- advanced
function AdvancedSection() {
  const wb = useWorkbench();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    void wb.refreshKernel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const k = wb.kernel;
  const specOn = wb.settings?.enable_specialists ?? false;

  const toggleSpecialists = async () => {
    setBusy("spec");
    setError(null);
    const err = await wb.changeSpecialists(!specOn);
    setBusy(null);
    if (err !== null) setError(err);
  };
  const restart = async () => {
    if (!wb.projectPath) return;
    setBusy("restart");
    setError(null);
    setMsg(null);
    try {
      await restartEngine(wb.projectPath);
      void wb.refreshSettings();
      void wb.refreshKernel();
      setMsg(t.modelEngineRestarted);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  const counts = t.advCatalogCounts
    .replace("{b}", String(k?.catalog?.n_bundled ?? "?"))
    .replace("{c}", String(k?.catalog?.n_custom ?? "?"));

  return (
    <div className="flex flex-col gap-4">
      {error && <AlertBanner>{error}</AlertBanner>}
      {msg && <div className="text-xs text-ok">{msg}</div>}
      <div className="flex items-center justify-between rounded-card border border-line p-3">
        <span className="text-sm text-ink" title={t.advSpecialistsTip}>
          {t.advSpecialists}
        </span>
        <span className="flex items-center gap-2">
          {busy === "spec" && <Spinner className="h-3 w-3 text-ink-3" />}
          <Switch
            checked={specOn}
            disabled={busy !== null || !wb.projectPath}
            title={t.advSpecialistsTip}
            onToggle={() => void toggleSpecialists()}
            label={t.advSpecialists}
          />
        </span>
      </div>

      <div className="rounded-card border border-line p-3" data-testid="kernel-info">
        <div className="mb-2 text-sm font-medium text-ink">{t.advKernel}</div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-2xs">
          <dt className="text-ink-3">{t.advKernelVersion}</dt>
          <dd className="font-mono text-ink">
            codex {k?.version ?? "—"}
            {k?.newest_installed && k.newest_installed !== k.version ? (
              <span className="ml-1 text-warn">{t.paren(`${t.advKernelNewer} ${k.newest_installed}`)}</span>
            ) : null}
          </dd>
          <dt className="text-ink-3">{t.advKernelSource}</dt>
          <dd className="font-mono text-ink-2">{k?.source ?? "—"}</dd>
          <dt className="text-ink-3">{t.advKernelPath}</dt>
          <dd className="truncate font-mono text-ink-2" title={k?.path ?? ""}>{k?.path ?? "—"}</dd>
          <dt className="text-ink-3">{t.advSdk}</dt>
          <dd className="font-mono text-ink-2">{k?.sdk_version ?? "—"}</dd>
          <dt className="text-ink-3">{t.advCatalog}</dt>
          <dd className="text-ink-2">
            {counts}
            {k?.catalog?.error ? <span className="ml-1 text-danger">{k.catalog.error}</span> : null}
          </dd>
          <dt className="text-ink-3">{t.advConfigPath}</dt>
          <dd className="truncate font-mono text-ink-2" title={k?.config_path ?? ""}>{k?.config_path ?? "—"}</dd>
        </dl>
        <p className="mt-2 text-2xs leading-relaxed text-ink-3">
          {t.advKernelUpdate}
          {k?.update_hint && k.update_hint !== t.advKernelUpdate ? (
            <span className="ml-1 font-mono">{k.update_hint}</span>
          ) : null}
        </p>
        {(k?.candidates?.length ?? 0) > 1 && (
          <div className="mt-2 flex flex-col gap-0.5 font-mono text-2xs text-ink-3">
            {k?.candidates.map((c) => (
              <div key={c.path} className="truncate" title={c.path}>
                {c.source} · {c.version ?? "?"} · {c.path}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-card border border-line p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-ink">{t.advOpenProjects}</span>
          <button
            type="button"
            disabled={busy !== null || !wb.projectPath}
            onClick={() => void restart()}
            className={btnCls}
          >
            {busy === "restart" ? t.advEngineRestarting : t.advEngineRestart}
          </button>
        </div>
        <div className="flex flex-col gap-1 font-mono text-2xs text-ink-2">
          {(k?.open_projects ?? []).map((p) => (
            <div key={p.path} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate" title={p.path}>{p.path}</span>
              <span className="text-ink-3">{p.kernel_version ?? "?"}</span>
              {p.busy && <span className="text-ok">{t.running}</span>}
              {p.restart_pending && <span className="text-warn">{t.modelRestartPending}</span>}
            </div>
          ))}
          {(k?.open_projects ?? []).length === 0 && <span className="text-ink-3">—</span>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- about
function AboutSection() {
  const wb = useWorkbench();
  const [build, setBuild] = useState<UiBuildInfo | null>(null);
  useEffect(() => {
    let alive = true;
    health()
      .then((h) => {
        if (alive) setBuild(h.ui_build ?? null);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return (
    <div className="flex flex-col gap-3 text-xs text-ink-2">
      <div>
        <span className="text-ink-3">{t.aboutBuild}{t.colon}</span>
        <span className="font-mono">{build?.version ?? "—"}</span>
        {build?.built_at ? <span className="ml-1 font-mono text-ink-3">{build.built_at}</span> : null}
        {build?.stale && <div className="mt-0.5 text-warn">{t.buildStale}</div>}
      </div>
      <div>
        <span className="text-ink-3">{t.advKernel}{t.colon}</span>
        <span className="font-mono">codex {wb.kernel?.version ?? "—"}</span>
        <span className="ml-1 font-mono text-ink-3">SDK {wb.kernel?.sdk_version ?? "—"}</span>
      </div>
      <Link to="/legacy" onClick={wb.closeSettings} className="text-ink-2 underline underline-offset-2 hover:text-ink">
        {t.aboutLegacy}
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------- dialog
export function SettingsDialog() {
  const wb = useWorkbench();
  const { section } = wb.settingsDialog;
  const close = wb.closeSettings;
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(dialogRef, close);

  return (
    <div
      className="dialog-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={t.settingsTitle}
      data-testid="settings-dialog"
    >
      <div ref={dialogRef} tabIndex={-1} className="settings-surface flex h-[650px] max-h-[92vh] w-[900px] max-w-[96vw] flex-col overflow-hidden bg-bg sm:flex-row">
        <nav className="flex w-full shrink-0 flex-row gap-px overflow-x-auto border-b border-line bg-surface p-2 sm:w-44 sm:flex-col sm:overflow-y-auto sm:border-r sm:border-b-0">
          <div className="hidden px-2 pt-1 pb-2 text-base font-semibold text-ink sm:block">{t.settingsTitle}</div>
          {SECTIONS.map((s) => {
            const Icon = SECTION_ICONS[s.id];
            return (
            <button
              key={s.id}
              type="button"
              data-testid={`settings-nav-${s.id}`}
              aria-current={section === s.id ? "page" : undefined}
              onClick={() => wb.openSettings(s.id)}
              className={cx(
                "settings-nav-button flex h-10 shrink-0 items-center gap-2.5 rounded-lg px-3 text-center text-sm transition-colors sm:text-left",
                section === s.id ? "bg-raised text-ink" : "text-ink-2 hover:bg-raised/60 hover:text-ink",
              )}
            >
              <Icon size={16} className="hidden shrink-0 opacity-70 sm:block" />{s.label}
            </button>
          ); })}
        </nav>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-start justify-between gap-3 px-6 pt-6 pb-5">
            <div><h2 className="text-xl font-medium tracking-tight text-ink">
              {SECTIONS.find((s) => s.id === section)?.label}
            </h2><p className="mt-1.5 text-sm leading-relaxed text-ink-3">{SECTION_DESCRIPTIONS[section]}</p></div>
            <button
              type="button"
              title={t.settingsClose}
              aria-label={t.settingsClose}
              onClick={close}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-3 transition-colors hover:bg-raised hover:text-ink"
            >
              <IconX size={14} />
            </button>
          </div>
          <div className="settings-content min-h-0 flex-1 overflow-y-auto px-6 pb-6">
            {section === "providers" && <ProvidersSection />}
            {section === "models" && <ModelsSection />}
            {section === "context" && <ContextSection />}
            {section === "appearance" && <AppearanceSection />}
            {section === "advanced" && <AdvancedSection />}
            {section === "about" && <AboutSection />}
          </div>
        </div>
      </div>
    </div>
  );
}
