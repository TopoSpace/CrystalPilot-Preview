/** Interface language for the end-to-end specs.
 *
 * The specs assert on the same dictionaries the interface renders, so they
 * run under either language: `CP_E2E_LANG=en npx playwright test` drives the
 * English interface, the default is Chinese. The browser is told the language
 * through the storage state in playwright.config.ts (the same localStorage
 * key the settings dialog writes). */
import { en, zh, type Strings } from "../src/lib/strings";

export type Lang = "zh" | "en";
export const LANG: Lang = process.env.CP_E2E_LANG === "en" ? "en" : "zh";
export const S: Strings = LANG === "en" ? en : zh;
export const LANGUAGE_STORAGE_KEY = "crystalpilot-language";

/** Escape a dictionary string for use inside a RegExp. */
export function rx(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
