/** Round-3 R2-B layout evidence on a REAL project: identity bar rows that do
 * not overflow, the extent menu regrouped into 范围 / 动作, the node tree
 * with branch headers and the diag/* family folded, artifacts grouped by
 * delivery, focus mode, sidebar display names, and the darker secondary
 * ink - at three window widths in both themes. Screenshots land in
 * workdir/ui-evidence/<round>/. Run:
 *   CP_EVIDENCE_ROUND=r3-r2b CP_E2E_PROJECT=<path> npx playwright test e2e/r2b-layout.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import {
  pickTarget,
  setTheme,
  shotPath,
  THEMES,
  threadUrl,
  watchErrors,
  type Target,
} from "./helpers";
import { S, rx } from "./lang";

const SIZES: ReadonlyArray<readonly [string, number, number]> = [
  ["900", 900, 650],
  ["1100", 1100, 700],
  ["1440", 1440, 900],
];

async function settle(page: Page, ms = 1000): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

const overflowOf = (el: Element): number => el.scrollWidth - el.clientWidth;

for (const theme of THEMES) {
  test.describe(`R2-B layout (${theme})`, () => {
    let target: Target | null = null;
    test.beforeAll(async ({ request }) => {
      target = await pickTarget(request);
    });

    for (const [name, width, height] of SIZES) {
      test(`${name}px: identity bar, extent menu, node tree, artifacts, focus`, async ({ page }) => {
        test.skip(target === null, "no real project with a node tree");
        await page.setViewportSize({ width, height });
        await setTheme(page, theme);
        const errors = watchErrors(page);
        await page.goto(threadUrl(target!));
        const pane = page.locator("aside");
        await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
        await settle(page, 2000);
        await page.screenshot({ path: shotPath(`${name}-${theme}-thread`) });

        // secondary ink is the darker R2-B token (light) / the lifted one (dark)
        const ink3 = await page.evaluate(() =>
          getComputedStyle(document.documentElement).getPropertyValue("--color-ink-3").trim(),
        );
        expect(ink3).toBe(theme === "light" ? "#605a52" : "#a7a297");

        // identity bar: two rows, neither overflowing, every truncation titled
        const row1 = pane.getByTestId("identity-row1");
        await expect(row1).toBeVisible();
        expect(await row1.evaluate(overflowOf)).toBeLessThanOrEqual(1);
        const untitled = await row1
          .locator(".truncate")
          .evaluateAll((els) => els.filter((e) => !e.getAttribute("title")).length);
        expect(untitled).toBe(0);
        const row2 = pane.getByTestId("identity-row2");
        if (await row2.count()) {
          expect(await row2.evaluate(overflowOf)).toBeLessThanOrEqual(1);
          expect(
            await row2.locator(".truncate").evaluateAll((els) => els.filter((e) => !e.getAttribute("title")).length),
          ).toBe(0);
        }

        // extent menu: 范围 (slices) above 动作 (grow / compaq)
        await pane.locator('button[aria-haspopup="menu"]').first().click();
        const menu = pane.getByRole("menu");
        await expect(menu).toBeVisible();
        expect(await menu.locator('[role="presentation"]').allTextContents()).toEqual([S.extentSecRange, S.extentSecAction]);
        const items = await menu.getByRole("menuitem").allTextContents();
        expect(items[0]).toContain(S.modeAsu);
        expect(items.at(-1)).toContain(S.assembleAsu);
        expect(items.findIndex((t) => t.includes(S.growShell))).toBeGreaterThan(
          items.findIndex((t) => t.includes(S.modeRange)),
        );
        await page.screenshot({ path: shotPath(`${name}-${theme}-extent-menu`) });
        await page.keyboard.press("Escape");
        await expect(menu).toHaveCount(0);

        // centre on a selected atom: the ADP badge selects a real atom
        const anomaly = pane.getByRole("button", { name: /ADP$/ }).first();
        if (await anomaly.count()) {
          await anomaly.click();
          const centre = pane.getByRole("button", { name: S.selCenter, exact: true });
          await expect(centre).toBeVisible();
          await centre.click();
          await settle(page, 700);
          await page.screenshot({ path: shotPath(`${name}-${theme}-centered`) });
          await pane.getByRole("button", { name: S.resetView, exact: true }).click();
          await pane.getByRole("button", { name: S.cancel, exact: true }).first().click().catch(() => undefined);
        }

        // node tree: branch headers, the diag family folded, a graph that fits
        await pane.getByRole("button", { name: new RegExp("^" + rx(S.tabNodes)) }).first().click();
        const tree = page.getByTestId("node-tree");
        await expect(tree).toBeVisible();
        await settle(page, 600);
        const branches = tree.getByTestId("tree-branch");
        expect(await branches.count()).toBeGreaterThan(0);
        const diag = tree.getByTestId("tree-diag");
        if (await diag.count()) {
          await expect(diag).toHaveAttribute("aria-expanded", "false");
        }
        const svgW = await tree.locator("svg").first().evaluate((el) => el.getBoundingClientRect().width);
        const paneW = (await pane.boundingBox())!.width;
        expect(svgW).toBeLessThan(paneW / 2);
        // folding the newest branch hides its nodes; unfolding brings them back
        const nodesBefore = await tree.getByTestId("tree-node").count();
        await branches.first().click();
        await settle(page, 300);
        expect(await tree.getByTestId("tree-node").count()).toBeLessThan(nodesBefore);
        await branches.first().click();
        await settle(page, 300);
        expect(await tree.getByTestId("tree-node").count()).toBe(nodesBefore);
        // the viewed node is marked, and the best refined node once anything was refined
        await expect(tree.locator('[data-testid="tree-node"][aria-current="true"]')).toHaveCount(1);
        await page.screenshot({ path: shotPath(`${name}-${theme}-nodes`) });

        // artifacts: grouped by delivery, no backslash paths on screen
        await pane.getByRole("button", { name: new RegExp("^" + rx(S.tabArtifacts)) }).first().click();
        await settle(page, 800);
        const panel = page.getByTestId("artifacts-panel");
        if (await panel.count()) {
          // groupArtifacts() puts anything that is not deliverable in the logs
          // section, so a thread that only ever wrote a transcript.jsonl has no
          // delivery group at all. Both shapes are correct; an empty shell is
          // not. (This asserted a group unconditionally and started failing
          // once the newest thread on the box was a bare connectivity check.)
          if (await panel.getByTestId("artifact-group").count()) {
            await expect(panel.getByTestId("artifact-group").first()).toBeVisible();
          } else {
            await expect(panel.getByTestId("artifact-logs")).toBeVisible();
          }
          const shown = await panel.locator('[data-testid="artifact-row"] span[title]').allTextContents();
          expect(shown.some((t) => t.includes("\\"))).toBe(false);
        }
        await page.screenshot({ path: shotPath(`${name}-${theme}-artifacts`) });

        // focus mode: >= 60 % for the structure, the conversation keeps a column, Esc leaves
        await pane.getByRole("button", { name: new RegExp("^" + rx(S.tabStructure)) }).first().click();
        await pane.getByTestId("focus-toggle").click();
        await settle(page, 900);
        expect(page.url()).toContain("focus=1");
        const asideW = (await pane.boundingBox())!.width;
        expect(asideW).toBeGreaterThanOrEqual(width * 0.6);
        expect((await page.locator("main").boundingBox())!.width).toBeGreaterThanOrEqual(300);
        await page.screenshot({ path: shotPath(`${name}-${theme}-focus`) });
        await page.keyboard.press("Escape");
        await settle(page, 500);
        expect(page.url()).not.toContain("focus=1");

        // sidebar: the project shows a name, scratch imports are folded away
        if (width >= 1200) {
          await expect(page.getByTestId("project-name")).toBeVisible();
          const primary = page.getByTestId("recent-primary");
          if (await primary.count()) {
            const labels = await primary.locator("span.truncate").allTextContents();
            expect(labels.some((l) => /^ui-import-\d+$/.test(l))).toBe(false);
          }
        }
        expect(errors.pageErrors).toEqual([]);
      });
    }
  });
}
