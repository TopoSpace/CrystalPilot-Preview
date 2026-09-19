/** Visual self-review (owner's ask, 2026-09-04): screenshots of the real
 * workbench at several window sizes and interaction states, so the layout
 * can be LOOKED at rather than assumed. Not an assertion suite - the
 * pictures are the deliverable; they land in workdir/ui-evidence/<round>/
 * (CP_EVIDENCE_ROUND, default "review"). Run:
 *   CP_EVIDENCE_ROUND=review-r6 npx playwright test e2e/visual-review.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, setTheme, shotPath, threadUrl, type Target } from "./helpers";

const SIZES: ReadonlyArray<readonly [string, number, number]> = [
  ["narrow", 1100, 700],
  ["laptop", 1366, 768],
  ["wide", 1920, 1080],
];

async function settle(page: Page, ms = 1200): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

test.describe("visual review", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
  });

  for (const [name, width, height] of SIZES) {
    test(`thread states at ${name} ${width}x${height}`, async ({ page }) => {
      test.skip(target === null, "no project with nodes on this machine");
      await page.setViewportSize({ width, height });
      await setTheme(page, "light");
      await page.goto(threadUrl(target!));
      const pane = page.locator("aside");
      await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
      await settle(page, 2500);
      await page.screenshot({ path: shotPath(`${name}-thread`) });

      // composer permission menu
      const permChip = page.locator("button", { hasText: /^(只读|Copilot|自动|完全访问)$/ }).first();
      if (await permChip.count()) {
        await permChip.click();
        await settle(page, 500);
        await page.screenshot({ path: shotPath(`${name}-permission-menu`) });
        await page.keyboard.press("Escape");
      }

      // right pane: 绘制 panel + 关系 panel
      await pane.getByRole("button", { name: /^绘制/ }).click();
      await settle(page, 500);
      await page.screenshot({ path: shotPath(`${name}-panel-draw`) });
      await page.keyboard.press("Escape");
      await pane.getByRole("button", { name: /^关系/ }).click();
      await settle(page, 500);
      await page.screenshot({ path: shotPath(`${name}-panel-relations`) });
      await page.keyboard.press("Escape");

      // header card toggled (it may start open or closed - the identity
      // bar is the only aria-expanded button in the pane)
      const headerToggle = pane.locator("button[aria-expanded]").first();
      await headerToggle.click();
      await settle(page, 500);
      await page.screenshot({ path: shotPath(`${name}-header-toggled`) });
      await headerToggle.click();

      // 分析 / 节点树 / 验证 tabs
      await pane.getByRole("button", { name: /^分析/ }).first().click();
      await expect(page.getByTestId("analysis-panel")).toBeVisible({ timeout: 90_000 });
      await settle(page, 1200);
      await page.screenshot({ path: shotPath(`${name}-analysis`) });
      await pane.getByRole("button", { name: /^节点树/ }).first().click();
      await settle(page, 800);
      await page.screenshot({ path: shotPath(`${name}-nodes`) });
      await pane.getByRole("button", { name: /^验证/ }).first().click();
      await settle(page, 800);
      await page.screenshot({ path: shotPath(`${name}-validation`) });

      // 详细 view mode
      const verbose = page.getByRole("button", { name: "详细" }).first();
      if (await verbose.count()) {
        await verbose.click();
        await settle(page, 800);
        await page.screenshot({ path: shotPath(`${name}-verbose`) });
        await page.getByRole("button", { name: "简洁" }).first().click();
      }
    });
  }

  test("dark theme at laptop size", async ({ page }) => {
    test.skip(target === null, "no project with nodes on this machine");
    await page.setViewportSize({ width: 1366, height: 768 });
    await setTheme(page, "dark");
    await page.goto(threadUrl(target!));
    const pane = page.locator("aside");
    await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
    await settle(page, 2500);
    await page.screenshot({ path: shotPath("laptop-dark-thread") });
    await pane.getByRole("button", { name: /^分析/ }).first().click();
    await expect(page.getByTestId("analysis-panel")).toBeVisible({ timeout: 90_000 });
    await settle(page, 1200);
    await page.screenshot({ path: shotPath("laptop-dark-analysis") });
  });
});
