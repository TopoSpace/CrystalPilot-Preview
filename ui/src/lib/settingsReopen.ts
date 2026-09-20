/**
 * Remember which settings section to reopen after a full page reload.
 *
 * Switching the interface language reloads the page (see i18n.ts). Without
 * this the dialog the user was in would simply be gone; with it the shell
 * reopens the same section once, so the switch is visible where it was made.
 */
const KEY = "crystalpilot-reopen-settings";

export function rememberSettingsSection(section: string): void {
  try {
    sessionStorage.setItem(KEY, section);
  } catch {
    // storage unavailable: the dialog just stays closed after the reload
  }
}

/** Return the remembered section once, clearing it. */
export function takeSettingsSection(): string | null {
  try {
    const section = sessionStorage.getItem(KEY);
    if (section) sessionStorage.removeItem(KEY);
    return section;
  } catch {
    return null;
  }
}
