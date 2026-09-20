/** 设置 → 提供方与密钥: Responses-compatible endpoints with explicit
 * managed-key / environment / no-auth modes. Stored secrets and sensitive
 * legacy header values are never echoed back. */
import { useEffect, useState } from "react";
import { AlertBanner, Spinner } from "../../components/ui";
import { cx } from "../../lib/format";
import {
  deleteProvider,
  setDefaultProvider,
  testProvider,
  upsertProvider,
} from "../../lib/wbApi";
import type { ProviderAuthMode, ProviderInfo, ProviderTestResult } from "../../lib/wbTypes";
import { t } from "../../lib/i18n";
import { useWorkbench } from "../../state/WorkbenchProvider";
import { shortProviderName } from "../composer/ModelMenu";

type EditableAuthMode = Exclude<ProviderAuthMode, "legacy">;
type FormAuthMode = EditableAuthMode | "preserve";

interface ProviderForm {
  isNew: boolean;
  id: string;
  name: string;
  base_url: string;
  wire_api: string;
  auth_mode: FormAuthMode;
  env_key: string;
  api_key: string;
  remove_api_key: boolean;
  headers: string;
  env_headers: string;
  query_params: string;
  request_max_retries: string;
  stream_max_retries: string;
  stream_idle_timeout_ms: string;
}

export interface ProviderPreset {
  id: string;
  label: string;
  name: string;
  base_url: string;
  headers: Record<string, string>;
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "crystalpilot",
    label: "CrystalPilot Gateway",
    name: "CrystalPilot Gateway (OpenAI Responses-compatible)",
    base_url: "https://gateway.example.com/openai",
    headers: {},
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    name: "OpenRouter (OpenAI Responses-compatible)",
    base_url: "https://openrouter.ai/api/v1",
    headers: { "X-Title": "CrystalPilot" },
  },
  {
    id: "openai-responses",
    label: "OpenAI",
    name: "OpenAI",
    base_url: "https://api.openai.com/v1",
    headers: {},
  },
  { id: "", label: "Responses-compatible", name: "", base_url: "", headers: {} },
];

export function mapToText(h: Record<string, string>): string {
  return Object.entries(h).map(([k, v]) => `${k}: ${v}`).join("\n");
}

export function textToMap(source: string, label = "mapping"): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of source.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const i = line.indexOf(":");
    if (i <= 0 || !line.slice(i + 1).trim()) {
      throw new Error(`${label}: ${t.providerMapLineInvalid}`);
    }
    const key = line.slice(0, i).trim();
    if (key in out) throw new Error(`${label}: ${t.providerMapDuplicate} ${key}`);
    out[key] = line.slice(i + 1).trim();
  }
  return out;
}

export function jsonToStringMap(text: string): Record<string, string> {
  if (!text.trim()) return {};
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(t.providerQueryInvalid);
  }
  if (!value || Array.isArray(value) || typeof value !== "object") {
    throw new Error(t.providerQueryInvalid);
  }
  const entries = Object.entries(value);
  if (entries.some(([, item]) => typeof item !== "string")) {
    throw new Error(t.providerQueryInvalid);
  }
  return Object.fromEntries(entries) as Record<string, string>;
}

function mapToJson(value: Record<string, string>): string {
  return Object.keys(value).length ? JSON.stringify(value, null, 2) : "";
}

function optionalInteger(value: string, label: string, maximum: number): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0 || parsed > maximum) {
    throw new Error(`${label}: ${t.providerNumberInvalid} 0–${maximum}`);
  }
  return parsed;
}

function fmtKeyDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function TestResultLine({ r }: { r: ProviderTestResult }) {
  if (r.ok) {
    const info = r.key_info;
    return (
      <div className="text-2xs text-ok" data-testid="provider-test-ok">
        {t.providerTestOk}
        {r.n_models !== undefined ? ` · ${r.n_models} ${t.providerModelsUnit}` : ""}
        {r.latency_ms !== undefined ? ` · ${r.latency_ms} ms` : ""}
        {r.used_stored_key ? t.paren(t.providerKeySet) : ""}
        {r.check === "model_catalogue" ? ` · ${t.providerCatalogueOnly}` : ""}
        {info && (
          <span className="ml-1 text-ink-3">
            {info.label ? `${info.label} · ` : ""}
            {info.usage !== undefined ? `usage ${info.usage}` : ""}
            {info.limit !== null && info.limit !== undefined ? ` / ${info.limit}` : ""}
          </span>
        )}
      </div>
    );
  }
  return (
    <div className="text-2xs text-danger" data-testid="provider-test-fail">
      {t.providerTestFail}
      {r.status ? t.paren(`HTTP ${r.status}`) : ""}
      {r.error ? `${t.colon}${r.error}` : ""}
    </div>
  );
}

const inputCls =
  "h-8 w-full min-w-0 rounded-lg border border-line bg-bg px-2.5 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-accent/60 disabled:opacity-50";
const btnCls =
  "h-7 rounded-md border border-line px-2.5 text-xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40";
/** secondary actions: quiet text, no border (the card already has one) */
const linkCls =
  "h-7 rounded-md px-1.5 text-xs text-ink-3 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40";

export function ProvidersSection() {
  const wb = useWorkbench();
  const [form, setForm] = useState<ProviderForm | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ProviderTestResult>>({});
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void wb.refreshProviders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentProvider = wb.settings?.model_provider ?? null;
  const defaultId = wb.providers.find((p) => p.is_default)?.id ?? null;
  const savedProvider = form ? wb.providers.find((p) => p.id === form.id) : undefined;
  const authNeedsSave = form !== null && (
    form.remove_api_key
    || (form.auth_mode !== "preserve"
      && form.auth_mode !== (savedProvider?.auth_mode ?? "managed_api_key"))
    || (form.auth_mode === "environment" && form.env_key.trim() !== (savedProvider?.env_key ?? ""))
    || form.env_headers !== mapToText(savedProvider?.env_http_headers ?? {})
  );

  const beginEdit = (p: ProviderInfo | null) => {
    setError(null);
    setMessage(null);
    setShowKey(false);
    setForm(
      p
        ? {
            isNew: false,
            id: p.id,
            name: p.name,
            base_url: p.base_url ?? "",
            wire_api: p.wire_api,
            auth_mode: p.auth_mode === "legacy" ? "preserve" : p.auth_mode,
            env_key: p.env_key ?? "",
            api_key: "",
            remove_api_key: false,
            headers: mapToText(p.http_headers),
            env_headers: mapToText(p.env_http_headers),
            query_params: mapToJson(p.query_params),
            request_max_retries: p.request_max_retries?.toString() ?? "",
            stream_max_retries: p.stream_max_retries?.toString() ?? "",
            stream_idle_timeout_ms: p.stream_idle_timeout_ms?.toString() ?? "",
          }
        : {
            isNew: true,
            id: "",
            name: "",
            base_url: "",
            wire_api: "responses",
            auth_mode: "managed_api_key",
            env_key: "",
            api_key: "",
            remove_api_key: false,
            headers: "",
            env_headers: "",
            query_params: "",
            request_max_retries: "",
            stream_max_retries: "",
            stream_idle_timeout_ms: "",
          },
    );
  };

  const applyPreset = (preset: ProviderPreset) => {
    if (!form) return;
    const existing = preset.id ? wb.providers.find((p) => p.id === preset.id) : undefined;
    if (existing) {
      beginEdit(existing);
      return;
    }
    setForm({
      ...form,
      id: preset.id,
      name: preset.name,
      base_url: preset.base_url,
      wire_api: "responses",
      auth_mode: "managed_api_key",
      env_key: "",
      api_key: "",
      remove_api_key: false,
      headers: mapToText(preset.headers),
    });
  };

  const runTest = async (key: string, body: Parameters<typeof testProvider>[0]) => {
    setTesting(key);
    setError(null);
    try {
      const r = await testProvider(body);
      setTestResults((prev) => ({ ...prev, [key]: r }));
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [key]: { ok: false, error: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setTesting(null);
    }
  };

  const testCurrentForm = () => {
    if (!form || authNeedsSave) return;
    try {
      void runTest("__form", {
        id: form.isNew ? null : form.id,
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim() === "" ? null : form.api_key,
        http_headers: textToMap(form.headers, t.providerHeaders),
        query_params: jsonToStringMap(form.query_params),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const save = async () => {
    if (!form || saving) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const headers = textToMap(form.headers, t.providerHeaders);
      const envHeaders = textToMap(form.env_headers, t.providerEnvHeaders);
      const queryParams = jsonToStringMap(form.query_params);
      await upsertProvider({
        id: form.id.trim(),
        name: form.name.trim() || null,
        base_url: form.base_url.trim(),
        wire_api: form.wire_api,
        auth_mode: form.auth_mode === "preserve" ? undefined : form.auth_mode,
        env_key: form.auth_mode === "environment" ? form.env_key.trim() : undefined,
        api_key: form.api_key.trim() === "" ? undefined : form.api_key,
        remove_api_key: form.remove_api_key,
        http_headers: headers,
        env_http_headers: envHeaders,
        query_params: queryParams,
        request_max_retries: optionalInteger(
          form.request_max_retries, t.providerRequestRetries, 100,
        ),
        stream_max_retries: optionalInteger(
          form.stream_max_retries, t.providerStreamRetries, 100,
        ),
        stream_idle_timeout_ms: optionalInteger(
          form.stream_idle_timeout_ms, t.providerIdleTimeout, 86_400_000,
        ),
      });
      await wb.refreshProviders();
      void wb.refreshSettings();
      setForm(null);
      setMessage(t.providerSaved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (p: ProviderInfo) => {
    if (busy) return;
    if (!window.confirm(t.providerDeleteConfirm)) return;
    setBusy(p.id);
    setError(null);
    try {
      await deleteProvider(p.id);
      await wb.refreshProviders();
      void wb.refreshSettings();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const makeDefault = async (p: ProviderInfo) => {
    if (busy) return;
    setBusy(p.id);
    setError(null);
    try {
      await setDefaultProvider(p.id);
      await wb.refreshProviders();
      void wb.refreshSettings();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const useInProject = async (p: ProviderInfo) => {
    if (busy) return;
    setBusy(p.id);
    setError(null);
    const err = await wb.patchSettings({
      model_provider_override: p.id === defaultId ? null : p.id,
    });
    setBusy(null);
    if (err !== null) setError(err);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs leading-relaxed text-ink-3">{t.providerKeyNote}</p>
        <button
          type="button"
          data-testid="provider-add"
          onClick={() => beginEdit(null)}
          className="ml-3 h-8 shrink-0 rounded-lg bg-ink px-3 text-xs font-medium text-bg transition-opacity hover:opacity-85"
        >
          {t.providerAdd}
        </button>
      </div>
      {wb.kernel?.config_path && (
        <details className="text-2xs text-ink-3">
          <summary className="cursor-pointer">{t.providerCurrentConfig}</summary>
          <code className="mt-1 block break-all">{wb.kernel.config_path}</code>
        </details>
      )}

      {error !== null && <AlertBanner>{error}</AlertBanner>}
      {message !== null && <div className="text-xs text-ok">{message}</div>}

      {form !== null && (
        <form
          data-testid="provider-form"
          className="flex flex-col gap-2.5 rounded-card border border-accent/30 bg-surface/60 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="text-sm font-medium text-ink">
            {form.isNew ? t.providerNew : form.name || form.id}
          </div>
          {form.isNew && (
            <div className="flex flex-wrap gap-1.5" data-testid="provider-presets">
              {PROVIDER_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  className={btnCls}
                  onClick={() => applyPreset(preset)}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <label className="flex min-w-0 flex-col gap-1 text-2xs text-ink-3">
              {t.providerId}
              <input
                value={form.id}
                data-testid="provider-id"
                disabled={!form.isNew}
                placeholder={t.providerIdHint}
                spellCheck={false}
                onChange={(e) => setForm({ ...form, id: e.target.value.toLowerCase() })}
                className={cx(inputCls, "font-mono")}
              />
            </label>
            <label className="flex flex-col gap-1 text-2xs text-ink-3">
              {t.providerName}
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className={inputCls}
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 text-2xs text-ink-3">
            {t.providerBaseUrl}
            <input
              value={form.base_url}
              data-testid="provider-base-url"
              placeholder={t.providerBaseUrlHint}
              spellCheck={false}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              className={cx(inputCls, "font-mono")}
            />
          </label>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <label className="flex min-w-0 flex-col gap-1 text-2xs text-ink-3">
              {t.providerProtocol}
              <select
                value={form.wire_api}
                data-testid="provider-protocol"
                onChange={(e) => setForm({ ...form, wire_api: e.target.value })}
                className={inputCls}
              >
                <option value="responses">OpenAI Responses · {t.providerNative}</option>
                <option value="chat" disabled>Chat Completions · {t.providerAdapterRequired}</option>
                <option value="completions" disabled>Legacy Completions · {t.providerAdapterRequired}</option>
                <option value="anthropic_messages" disabled>Anthropic Messages · {t.providerAdapterRequired}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-2xs text-ink-3">
              {t.providerAuthMode}
              <select
                value={form.auth_mode}
                data-testid="provider-auth-mode"
                onChange={(e) => setForm({
                  ...form,
                  auth_mode: e.target.value as FormAuthMode,
                  api_key: "",
                  remove_api_key: false,
                })}
                className={inputCls}
              >
                {form.auth_mode === "preserve" && (
                  <option value="preserve">{t.providerAuthPreserve}</option>
                )}
                <option value="managed_api_key">{t.providerAuthManaged}</option>
                <option value="environment">{t.providerAuthEnvironment}</option>
                <option value="none">{t.providerAuthNone}</option>
              </select>
            </label>
          </div>
          <p className="text-2xs leading-relaxed text-ink-3">{t.providerProtocolHelp}</p>
          {form.auth_mode === "environment" && (
            <label className="flex flex-col gap-1 text-2xs text-ink-3">
              {t.providerEnvKey}
              <input
                value={form.env_key}
                placeholder="OPENAI_API_KEY"
                spellCheck={false}
                onChange={(e) => setForm({ ...form, env_key: e.target.value })}
                className={cx(inputCls, "font-mono")}
              />
            </label>
          )}
          {form.auth_mode === "managed_api_key" && (
            <label className="flex flex-col gap-1 text-2xs text-ink-3">
              {t.providerApiKey}
              <span className="flex gap-1.5">
                <input
                  type={showKey ? "text" : "password"}
                  value={form.api_key}
                  disabled={form.remove_api_key}
                  placeholder={t.providerKeyPlaceholder}
                  autoComplete="off"
                  spellCheck={false}
                  data-testid="provider-key"
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  className={cx(inputCls, "font-mono")}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  className={cx(btnCls, "h-8 shrink-0")}
                >
                  {showKey ? t.providerHideKey : t.providerShowKey}
                </button>
              </span>
              {!form.isNew && wb.providers.find((p) => p.id === form.id)?.has_key && (
                <label className="flex items-center gap-1.5 text-2xs text-danger">
                  <input
                    type="checkbox"
                    checked={form.remove_api_key}
                    onChange={(e) => setForm({
                      ...form, remove_api_key: e.target.checked, api_key: "",
                    })}
                  />
                  {t.providerRemoveKey}
                </label>
              )}
            </label>
          )}
          {form.auth_mode === "preserve" && (
            <p className="text-2xs text-warn">{t.providerAuthPreserveHelp}</p>
          )}
          <details className="text-2xs text-ink-3" data-testid="provider-advanced">
            <summary className="cursor-pointer">{t.providerAdvanced}</summary>
            <div className="mt-2 flex flex-col gap-2.5">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {([
                  ["request_max_retries", t.providerRequestRetries, "100"],
                  ["stream_max_retries", t.providerStreamRetries, "100"],
                  ["stream_idle_timeout_ms", t.providerIdleTimeout, "86400000"],
                ] as const).map(([field, label, max]) => (
                  <label key={field} className="flex flex-col gap-1">
                    {label}
                    <input
                      type="number"
                      min="0"
                      max={max}
                      value={form[field]}
                      onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                      className={cx(inputCls, "font-mono")}
                    />
                  </label>
                ))}
              </div>
              <label className="flex flex-col gap-1">
                {t.providerHeaders}
                <textarea
                  value={form.headers}
                  rows={3}
                  spellCheck={false}
                  onChange={(e) => setForm({ ...form, headers: e.target.value })}
                  className="w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent/60"
                />
              </label>
              <label className="flex flex-col gap-1">
                {t.providerEnvHeaders}
                <textarea
                  value={form.env_headers}
                  rows={2}
                  placeholder="X-Api-Key: PROVIDER_API_KEY"
                  spellCheck={false}
                  onChange={(e) => setForm({ ...form, env_headers: e.target.value })}
                  className="w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent/60"
                />
              </label>
              <label className="flex flex-col gap-1">
                {t.providerQueryParams}
                <textarea
                  value={form.query_params}
                  rows={3}
                  placeholder={'{"api-version": "2026-01-01"}'}
                  spellCheck={false}
                  onChange={(e) => setForm({ ...form, query_params: e.target.value })}
                  className="w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent/60"
                />
              </label>
            </div>
          </details>
          {testResults.__form && <TestResultLine r={testResults.__form} />}
          {authNeedsSave && <p className="text-2xs text-ink-3">{t.providerAuthChanged}</p>}
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={testing !== null || form.base_url.trim() === "" || authNeedsSave}
              data-testid="provider-test"
              onClick={testCurrentForm}
              className={btnCls}
            >
              {testing === "__form" ? t.providerTesting : t.providerTest}
            </button>
            <div className="flex-1" />
            <button type="button" onClick={() => setForm(null)} className={btnCls}>
              {t.settingsClose}
            </button>
            <button
              type="submit"
              disabled={saving || form.id.trim() === "" || form.base_url.trim() === ""}
              data-testid="provider-save"
              className="h-7 rounded-md bg-ink px-3 text-xs font-medium text-bg transition-opacity hover:opacity-85 disabled:opacity-40"
            >
              {saving ? t.providerSaving : t.providerSave}
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-col gap-2" data-testid="provider-list">
        {wb.providers.map((p) => {
          const isCurrent = currentProvider === p.id;
          const r = testResults[p.id];
          return (
            <div
              key={p.id}
              className={cx(
                "provider-card rounded-card border p-4",
                isCurrent ? "border-accent/30" : "border-line",
              )}
              data-testid={`provider-${p.id}`}
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                <span className="text-sm font-medium text-ink" title={p.name}>
                  {shortProviderName(p.name, p.id)}
                </span>
                {!p.protocol_compatible && <span className="text-xs text-warn">{p.wire_api} · {t.providerUnsupported}</span>}
                {p.is_default && (
                  <span className="rounded-full bg-raised px-2 py-0.5 text-2xs text-ink-2">
                    {t.providerDefaultTag}
                  </span>
                )}
                {isCurrent && (
                  <span className="rounded-full bg-accent/8 px-2 py-0.5 text-2xs text-accent">
                    {t.providerUsedByProject}
                  </span>
                )}
              </div>
              <div className="mt-2 truncate text-xs text-ink-3" title={p.base_url ?? ""}>
                {p.base_url ?? "—"}
              </div>
              <div className="mt-1 text-2xs">
                <span className="text-ink-3">{t.providerAuthMode}{t.colon}</span>
                {p.auth_mode === "legacy" ? (
                  <span className="text-ink-2">{t.providerAuthExternal}</span>
                ) : p.auth_mode === "environment" ? (
                  <span className={p.has_key ? "text-ink-2" : "text-warn"}>
                    {p.has_key ? t.providerKeySet : t.providerEnvUnavailable}{t.paren(p.env_key ?? "")}
                  </span>
                ) : p.auth_mode === "none" ? (
                  <span className="text-ink-2">{t.providerAuthNone}</span>
                ) : p.has_key ? (
                  <span className="text-ink-2">
                    {t.providerKeySet}
                    {p.key_updated ? ` · ${t.providerKeyUpdated} ${fmtKeyDate(p.key_updated)}` : ""}
                  </span>
                ) : (
                  <span className="text-warn">{t.providerKeyUnset}</span>
                )}
              </div>
              {r && (
                <div className="mt-1">
                  <TestResultLine r={r} />
                </div>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <button type="button" onClick={() => beginEdit(p)} className={btnCls}>
                  {t.providerEdit}
                </button>
                <button
                  type="button"
                  disabled={testing !== null}
                  onClick={() => void runTest(p.id, { id: p.id })}
                  className={btnCls}
                >
                  {testing === p.id ? t.providerTesting : t.providerTest}
                </button>
                {!p.is_default && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void makeDefault(p)}
                    className={linkCls}
                  >
                    {t.providerSetDefault}
                  </button>
                )}
                {!isCurrent && wb.projectPath && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void useInProject(p)}
                    className={linkCls}
                  >
                    {t.providerUseInProject}
                  </button>
                )}
                <div className="flex-1" />
                {!p.is_default && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void remove(p)}
                    className={cx(linkCls, "text-ink-3 hover:text-danger")}
                  >
                    {busy === p.id ? <Spinner className="h-3 w-3" /> : t.providerDelete}
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {wb.providers.length === 0 && (
          <div className="text-xs text-ink-3">{t.modelLoading}</div>
        )}
      </div>
    </div>
  );
}
