/** Round-3 R5 evidence on a REAL project: the "长满" (grow-all) action with
 * its completion / truncation disclosure, and the analysis tab's pores
 * block with the pore-limiting diameter along a / b / c and the two
 * electron-count masks named side by side. Screenshots land in
 * workdir/ui-evidence/<round>/. Run:
 *   CP_EVIDENCE_ROUND=r3-r5 CP_E2E_PROJECT=<path> npx playwright test e2e/r5-analysis.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, setTheme, shotPath, THEMES, threadUrl, watchErrors, type Target } from "./helpers";
import { S, rx } from "./lang";

async function settle(page: Page, ms = 1000): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

const tag = (process.env.CP_E2E_TAG ?? "").replace(/[^a-z0-9-]/gi, "");
const nameOf = (base: string, theme: string) => (tag ? `${tag}-` : "") + `${base}-${theme}`;

for (const theme of THEMES) {
  test.describe(`R5 (${theme})`, () => {
    let target: Target | null = null;
    test.beforeAll(async ({ request }) => {
      target = await pickTarget(request);
    });

    test("grow-all disclosure and the analysis pores block", async ({ page }) => {
      test.skip(target === null, "no real project with a node tree");
      test.setTimeout(420_000);
      await page.setViewportSize({ width: 1440, height: 900 });
      await setTheme(page, theme);
      const errors = watchErrors(page);
      await page.goto(threadUrl(target!));
      const pane = page.locator("aside");
      await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
      await settle(page, 2000);

      // 长满: the scene request carries grow_all=1 and the response says
      // whether the fragment(s) completed or where growth stopped
      await pane.locator('button[aria-haspopup="menu"]').first().click();
      const menu = pane.getByRole("menu");
      await expect(menu).toBeVisible();
      const grown = page.waitForResponse(
        (r) => r.url().includes("/api/wb/refine/scene") && r.url().includes("grow_all=1"),
        { timeout: 120_000 },
      );
      await menu.getByRole("menuitem", { name: new RegExp(rx(S.growAll)) }).click();
      const scene = (await (await grown).json()) as {
        grow_all?: { complete: boolean; periodic_edges: number; caps: number; n_added: number; budget_hit: boolean };
        meta?: { n_atoms: number };
      };
      expect(scene.grow_all).toBeTruthy();
      const g = scene.grow_all!;
      expect(g.complete || g.periodic_edges > 0 || g.budget_hit).toBe(true);
      test.info().annotations.push({
        type: "grow_all",
        description: `complete=${g.complete} n_atoms=${scene.meta?.n_atoms} n_added=${g.n_added} periodic_edges=${g.periodic_edges} caps=${g.caps} budget_hit=${g.budget_hit}`,
      });
      await settle(page, 1500);
      if (!g.complete) {
        await expect(pane.getByText(g.budget_hit ? S.growAllBudget : S.growAllPeriodic)).toBeVisible();
      }
      await page.screenshot({ path: shotPath(nameOf("grow-all", theme)) });

      // analysis tab: pores block with axial PLD and both electron totals
      await pane.getByRole("button", { name: S.tabAnalysis, exact: true }).click();
      await expect(page.getByTestId("analysis-panel")).toBeVisible();
      // the stage notice is replaced by the section once the stage is ready
      const pores = page.getByTestId("analysis-pores");
      await expect(pores.or(page.locator('[data-testid="analysis-stage-pores"][data-status="error"]')))
        .toBeVisible({ timeout: 300_000 });
      test.skip((await pores.count()) === 0, "pores stage errored on this project");
      await pores.scrollIntoViewIfNeeded();
      await settle(page, 800);
      const text = await pores.innerText();
      const hasVoid = /V\d+/.test(text) && !text.includes(S.anNoVoids);
      test.info().annotations.push({ type: "pores", description: text.replace(/\s+/g, " ").slice(0, 600) });
      if (hasVoid) {
        expect(text).toContain(S.anPldAlong);
        expect(text).toContain(S.anElectronsRecomputed);
      }
      await page.screenshot({ path: shotPath(nameOf("analysis-pores", theme)) });
      const topo = page.getByTestId("analysis-topology");
      if (await topo.count()) {
        await topo.scrollIntoViewIfNeeded();
        await settle(page, 500);
        await page.screenshot({ path: shotPath(nameOf("analysis-topology", theme)) });
      }
      expect(errors.pageErrors).toEqual([]);
    });
  });
}
