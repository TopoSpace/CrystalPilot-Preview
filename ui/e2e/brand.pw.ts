/** Logo wiring (design/CrystalPilot-logo-v1 -> ui/public/brand/): the mark
 * in the sidebar brand row, the app icon on the welcome hero and project
 * home, the favicon following the theme, and how the mark reads at
 * 16/24/32 px. Screenshots land in workdir/ui-evidence/<round>/brand-*.png.
 * Run from ui/:  CP_E2E_PROJECT=<copy> npx playwright test e2e/brand.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";

const project = process.env.CP_E2E_PROJECT ?? null;

async function setTheme(page: Page, theme: "light" | "dark"): Promise<void> {
  await page.evaluate((t) => localStorage.setItem("crystalpilot-theme", t), theme);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
}

async function faviconHref(page: Page): Promise<string | null> {
  return page.evaluate(() => document.querySelector('link[rel="icon"]')?.getAttribute("href") ?? null);
}

test.describe("brand assets", () => {
  test("welcome hero and sidebar show the mark; favicon follows the theme", async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/");
    await expect(page.getByTestId("workbench-brand")).toContainText("CrystalPilot");
    await expect(page.getByTestId("workbench-brand").getByTestId("brand-mark")).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      const hero = page.locator('[data-testid="brand-mark"][data-variant="app"]');
      await expect(hero.first()).toBeVisible();
      await expect(hero.first()).toHaveAttribute("data-theme", theme);
      expect(await faviconHref(page)).toBe(`/brand/crystalpilot-app-${theme}.svg`);
      // the images actually load (naturalWidth > 0), i.e. the files are served
      const loaded = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLImageElement>('img[data-testid="brand-mark"]'))
        .map((img) => img.complete && img.naturalWidth > 0));
      expect(loaded.length).toBeGreaterThan(0);
      expect(loaded.every(Boolean)).toBe(true);
      await page.screenshot({ path: shotPath(`brand-welcome-${theme}`) });
    }
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });

  test("project home shows the app icon above the title", async ({ page }) => {
    test.skip(project === null, "CP_E2E_PROJECT not set");
    await page.goto(projectUrl(project!));
    const hero = page.locator('[data-testid="brand-mark"][data-variant="app"]');
    await expect(hero.first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("new-thread-target")).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: shotPath("brand-project-home") });
  });

  test("display mode keeps the mark next to the custom name", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("crystalpilot-presentation", JSON.stringify({ enabled: true, name: "TopoSpace · 晶体研究" })));
    await page.reload();
    await expect(page.getByTestId("workbench-brand")).toHaveText("TopoSpace · 晶体研究");
    await expect(page.getByTestId("workbench-brand").getByTestId("brand-mark")).toBeVisible();
    await page.screenshot({ path: shotPath("brand-display-mode") });
    await page.evaluate(() => localStorage.removeItem("crystalpilot-presentation"));
  });

  test("the mark stays legible at 16, 24 and 32 px", async ({ page }) => {
    await page.goto("/");
    // render the four SVGs at favicon sizes on a neutral page and keep the picture
    await page.setContent(`
      <body style="margin:0;padding:24px;background:#fff;font:12px system-ui;display:flex;gap:32px">
        ${["light", "dark"].map((t) => `
          <div style="display:flex;flex-direction:column;gap:12px;padding:16px;background:${t === "dark" ? "#111525" : "#fff"};color:${t === "dark" ? "#fff" : "#000"}">
            ${[16, 24, 32, 48].map((s) => `<div style="display:flex;align-items:center;gap:12px">
              <img src="/brand/crystalpilot-app-${t}.svg" width="${s}" height="${s}">
              <img src="/brand/crystalpilot-symbol.svg" width="${s}" height="${s}">
              <img src="/brand/crystalpilot-monochrome.svg" width="${s}" height="${s}" style="color:${t === "dark" ? "#fff" : "#000"}">
              <span>${s} px</span></div>`).join("")}
          </div>`).join("")}
      </body>`);
    const loaded = await page.evaluate(() => new Promise<boolean[]>((resolve) => {
      const imgs = Array.from(document.images);
      const check = () => { if (imgs.every((i) => i.complete)) resolve(imgs.map((i) => i.naturalWidth > 0)); else setTimeout(check, 50); };
      check();
    }));
    expect(loaded).toHaveLength(24);
    expect(loaded.every(Boolean)).toBe(true);
    await page.screenshot({ path: shotPath("brand-small-sizes"), clip: { x: 0, y: 0, width: 520, height: 260 } });
  });
});
