/** Appearance-only checks against the real CrystalPilot server.
 * Run: npx playwright test e2e/appearance.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { shotPath, watchErrors } from "./helpers";

const PALETTES = ["anthropic", "openai", "kimi"] as const;
const MODES = [
  { label: "浅色", value: "light" },
  { label: "深色", value: "dark" },
] as const;

async function openAppearance(page: Page): Promise<void> {
  const settings = page.getByTestId("open-settings");
  if (!(await settings.isVisible().catch(() => false))) {
    await page.getByRole("button", { name: "打开侧栏", exact: true }).click();
    await expect(settings).toBeVisible();
  }
  await settings.click();
  const dialog = page.getByTestId("settings-dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByTestId("settings-nav-appearance").click();
  await expect(dialog.getByTestId("appearance-settings")).toBeVisible();
}

test("palette and light/dark choices persist", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1200, height: 820 });
  const errors = watchErrors(page);
  await page.goto("/");
  await openAppearance(page);

  for (const palette of PALETTES) {
    const card = page.getByTestId(`palette-${palette}`);
    await card.click();
    await expect(card).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("html")).toHaveAttribute("data-palette", palette);
    await expect.poll(() => page.evaluate(() => localStorage.getItem("crystalpilot-palette"))).toBe(palette);

    for (const mode of MODES) {
      await page.getByRole("button", { name: mode.label, exact: true }).click();
      await expect.poll(() => page.locator("html").evaluate((el) => el.classList.contains("dark"))).toBe(mode.value === "dark");
      await expect.poll(() => page.evaluate(() => localStorage.getItem("crystalpilot-theme"))).toBe(mode.value);
      await page.screenshot({ path: shotPath(`appearance-${palette}-${mode.value}`) });
    }
  }

  await page.reload();
  await openAppearance(page);
  await expect(page.getByTestId("palette-kimi")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "深色", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});

test("legacy theme preference and invalid values are safe before first paint", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    localStorage.setItem("crystalpilot-theme", "dark");
    localStorage.setItem("crystalpilot-palette", "old-palette");
    localStorage.setItem("crystalpilot-font-size", "99");
  });
  await page.goto("/");

  const root = page.locator("html");
  await expect(root).toHaveClass(/dark/);
  await expect(root).toHaveAttribute("data-palette", "anthropic");
  expect(await root.evaluate((el) => getComputedStyle(el).getPropertyValue("--cp-scale").trim())).toBe("1.0000");
});

test("appearance settings fit a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 720 });
  await page.goto("/");
  await openAppearance(page);

  const dialog = page.getByTestId("settings-dialog");
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(box!.y + box!.height).toBeLessThanOrEqual(720);
  await expect(page.getByTestId("palette-anthropic")).toBeVisible();
  await expect(page.getByTestId("palette-openai")).toBeVisible();
  await expect(page.getByTestId("palette-kimi")).toBeVisible();
  await page.screenshot({ path: shotPath("appearance-narrow") });
});
