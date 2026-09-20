/**
 * Interface language.
 *
 * The language is chosen once per page load: it is read from localStorage at
 * module initialisation and every string in the interface is taken from that
 * language's dictionary (`t`). Switching languages therefore reloads the page;
 * `setLanguage` stores the choice and does the reload. The default is
 * Chinese, the language the workbench was written in.
 */
import { en, zh, type Strings } from "./strings";

export type Language = "zh" | "en";

export const LANGUAGE_STORAGE_KEY = "crystalpilot-language";
/** Request header the server reads to localise the few texts it composes itself. */
export const LANGUAGE_HEADER = "X-CrystalPilot-Language";
export const LANGUAGES: readonly Language[] = ["zh", "en"];
export const DEFAULT_LANGUAGE: Language = "zh";

/** Native names, shown in the language switch regardless of the active language. */
export const LANGUAGE_NAMES: Record<Language, string> = { zh: "中文", en: "English" };

export function isLanguage(value: unknown): value is Language {
  return value === "zh" || value === "en";
}

export function readLanguage(): Language {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(stored) ? stored : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

/** The language this page was loaded with. */
export const language: Language = readLanguage();

/** BCP 47 tag for the active language (`<html lang>`, Intl formatting). */
export function localeTag(lang: Language = language): string {
  return lang === "en" ? "en-US" : "zh-CN";
}

/** Every string the interface shows, in the active language. */
export const t: Strings = language === "en" ? en : zh;

export type StringKey = keyof Strings;

/**
 * Store a new interface language and reload so that every module picks it up.
 * `reload: false` only records the choice (used by tests).
 */
export function setLanguage(next: Language, options: { reload?: boolean } = {}): void {
  if (!isLanguage(next)) return;
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch {
    // private mode or storage disabled: the choice lasts for this page only
  }
  if (typeof document !== "undefined") document.documentElement.lang = localeTag(next);
  if (options.reload !== false && typeof window !== "undefined") window.location.reload();
}

/** Display label for a permission mode. */
export function permissionLabel(mode: string): string {
  switch (mode) {
    case "readonly":
      return t.permReadonly;
    case "copilot":
      return t.permCopilot;
    case "auto":
      return t.permAuto;
    case "full":
      return t.permFull;
    default:
      return mode;
  }
}

export function permissionDesc(mode: string): string {
  switch (mode) {
    case "readonly":
      return t.permReadonlyDesc;
    case "copilot":
      return t.permCopilotDesc;
    case "auto":
      return t.permAutoDesc;
    case "full":
      return t.permFullDesc;
    default:
      return "";
  }
}

/** "gpt-5.6-sol" -> "5.6 Sol"; unknown ids pass through. */
export function formatModel(model: string | null | undefined): string {
  if (!model) return "";
  const parts = model.replace(/^gpt-/, "").split("-");
  return parts
    .map((p) => (/^[a-z]/.test(p) ? p.charAt(0).toUpperCase() + p.slice(1) : p))
    .join(" ");
}

/** Reasoning effort -> label in the active language ("xhigh" -> 极高 / Extra high). */
export function formatEffort(effort: string | null | undefined): string {
  if (!effort) return "";
  return t.effortLabels[effort] ?? effort;
}
