/** The language switch in Settings > Appearance: the page reloads in the
 * other language, comes back to the same settings section, the choice is
 * stored in the browser and the server remembers it for the agent side.
 * Run: npx playwright test e2e/language.pw.ts (CP_E2E_LANG=en for the
 * English starting point). */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { en, zh } from "../src/lib/strings";
import { shotPath, watchErrors } from "./helpers";
import { LANG, LANGUAGE_STORAGE_KEY, S, type Lang } from "./lang";

const OTHER: Lang = LANG === "en" ? "zh" : "en";
const DICT = { zh, en } as const;
const LOCALE = { zh: "zh-CN", en: "en-US" } as const;
const NAMES = { zh: "中文", en: "English" } as const;

async function openAppearance(page: Page, dict: typeof zh): Promise<void> {
  const settings = page.getByTestId("open-settings");
  if (!(await settings.isVisible().catch(() => false))) {
    await page.getByRole("button", { name: dict.sidebarOpen, exact: true }).click();
    await expect(settings).toBeVisible();
  }
  await settings.click();
  const dialog = page.getByTestId("settings-dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByTestId("settings-nav-appearance").click();
  await expect(dialog.getByTestId("appearance-settings")).toBeVisible();
}

async function serverLanguage(request: APIRequestContext): Promise<string> {
  const res = await request.get("/api/language");
  expect(res.ok()).toBe(true);
  return ((await res.json()) as { language: string }).language;
}

test("switching the language reloads the interface, reopens the settings and reaches the server", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors = watchErrors(page);
  const serverBefore = await serverLanguage(request);
  try {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", LOCALE[LANG]);
    await openAppearance(page, S);
    const control = page.getByTestId("language-settings");
    await expect(control).toBeVisible();
    await expect(control.getByRole("button", { name: NAMES[LANG], exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: shotPath(`language-before-${LANG}`) });

    // switch: the page reloads in the other language and the dialog comes back
    await control.getByRole("button", { name: NAMES[OTHER], exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", LOCALE[OTHER]);
    await expect.poll(() => page.evaluate((k) => localStorage.getItem(k), LANGUAGE_STORAGE_KEY)).toBe(OTHER);
    const dialog = page.getByTestId("settings-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("appearance-settings")).toBeVisible();
    await expect(dialog.getByTestId("language-settings").getByRole("button", { name: NAMES[OTHER], exact: true })).toHaveAttribute("aria-pressed", "true");
    // a label outside the dialog is in the other language now
    await expect(page.getByTestId("open-settings")).toHaveAttribute("aria-label", DICT[OTHER].settings);
    // the server remembers the choice for the agent template and new threads
    await expect.poll(() => serverLanguage(request)).toBe(OTHER);
    await page.screenshot({ path: shotPath(`language-after-${OTHER}`) });

    // and back
    await dialog.getByTestId("language-settings").getByRole("button", { name: NAMES[LANG], exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("lang", LOCALE[LANG]);
    await expect(page.getByTestId("settings-dialog").getByTestId("appearance-settings")).toBeVisible();
    await expect(page.getByTestId("open-settings")).toHaveAttribute("aria-label", S.settings);
    await expect.poll(() => serverLanguage(request)).toBe(LANG);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  } finally {
    // leave the server as it was found
    await request.post("/api/language", { data: { language: serverBefore } });
  }
});

test("the server rejects an unsupported language and reports the current one", async ({ request }) => {
  const current = await serverLanguage(request);
  expect(["zh", "en"]).toContain(current);
  const bad = await request.post("/api/language", { data: { language: "fr" } });
  expect(bad.status()).toBe(400);
  expect(await serverLanguage(request)).toBe(current);
});
