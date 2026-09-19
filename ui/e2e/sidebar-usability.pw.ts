import { expect, test } from "@playwright/test";
import { pickTarget, setTheme, shotPath, THEMES, threadUrl, watchErrors, type Target } from "./helpers";

for (const theme of THEMES) {
  test.describe(`sidebar usability (${theme})`, () => {
    let target: Target | null = null;
    test.beforeAll(async ({ request }) => {
      target = await pickTarget(request);
    });

    for (const fontSize of [13, 16]) {
      test(`300px panel with ${fontSize}px text keeps controls and evidence usable`, async ({ page }) => {
        test.skip(target === null, "no real project with a node tree");
        await page.setViewportSize({ width: 1100, height: 700 });
        await setTheme(page, theme);
        await page.addInitScript((size: number) => {
          localStorage.setItem("wb.rightPaneWidth", "300");
          localStorage.setItem("crystalpilot-font-size", String(size));
        }, fontSize);
        const errors = watchErrors(page);
        const sceneReady = page.waitForResponse(
          (r) => r.url().includes("/api/wb/refine/scene?") && r.status() === 200,
        );
        await page.goto(threadUrl(target!));
        const scene = await (await sceneReady).json() as { node: string };
        const pane = page.locator("aside");
        const canvas = pane.locator("canvas").first();
        await expect(canvas).toBeVisible({ timeout: 60_000 });
        const reset = pane.getByRole("button", { name: "重置视角", exact: true });
        await expect(reset).toBeVisible();
        const paneBox = (await pane.boundingBox())!;
        const resetBox = (await reset.boundingBox())!;
        expect(resetBox.x + resetBox.width).toBeLessThanOrEqual(paneBox.x + paneBox.width);

        const fonts = await pane.locator('[class*="text-2xs"]').evaluateAll((els) => els
          .filter((el) => el.getBoundingClientRect().width > 0)
          .map((el) => Number.parseFloat(getComputedStyle(el).fontSize)));
        expect(fonts.length).toBeGreaterThan(0);
        expect(Math.min(...fonts)).toBeGreaterThanOrEqual(11);
        await page.screenshot({ path: shotPath(`sidebar-300-${fontSize}-${theme}`) });

        await pane.getByTitle("展开结构卡", { exact: true }).click();
        await pane.locator('button[aria-haspopup="menu"]').first().click();
        const menu = pane.getByRole("menu");
        const menuBox = (await menu.boundingBox())!;
        const canvasBox = (await canvas.boundingBox())!;
        expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(canvasBox.y + canvasBox.height);
        const last = menu.getByRole("menuitem", { name: /^装配非对称单元/ });
        await last.scrollIntoViewIfNeeded();
        const lastBox = (await last.boundingBox())!;
        expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(canvasBox.y + canvasBox.height);
        await page.screenshot({ path: shotPath(`sidebar-menu-300-${fontSize}-${theme}`) });
        await page.keyboard.press("Escape");
        await pane.getByTitle("收起结构卡", { exact: true }).click();

        // A real ADP flag selects a real atom without a pixel-coordinate guess.
        const anomaly = pane.getByRole("button", { name: /ADP$/ }).first();
        if (await anomaly.count()) {
          await anomaly.click();
          await pane.getByRole("button", { name: "在对话中引用", exact: true }).click();
          const draft = page.locator("textarea").first();
          await expect(draft).toHaveValue(new RegExp(`\\[anchor node=${scene.node} atoms=`));
          await expect(draft).toHaveValue(/Å²/);
          await page.screenshot({ path: shotPath(`sidebar-quote-300-${fontSize}-${theme}`) });
        }
        expect(errors.pageErrors).toEqual([]);
        expect(errors.consoleErrors).toEqual([]);
      });
    }
  });
}
