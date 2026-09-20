/** Evidence screenshots of the real workbench on a real project, both
 * themes: project home, thread view with every right-pane tab, grow x2 and
 * supercell. Assertions are structural (tabs, viewer canvas, no uncaught
 * errors); the pictures are the record humans review. */
import { expect, test, type Page } from "@playwright/test";
import {
  pickTarget,
  projectUrl,
  setTheme,
  shotPath,
  THEMES,
  threadUrl,
  watchErrors,
  type ErrorLog,
  type Target,
} from "./helpers";
import { S, rx } from "./lang";

/** Tab and panel buttons carry a count or hint after the label. */
const startsWith = (label: string): RegExp => new RegExp("^" + rx(label));

function expectNoErrors(errs: ErrorLog): void {
  test.info().annotations.push({ type: "gpu_noise", description: String(errs.gpuNoise.length) });
  expect(errs.pageErrors, "uncaught page errors").toEqual([]);
  expect(errs.consoleErrors, "console errors").toEqual([]);
}

async function settle(page: Page, ms = 1500): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

const TABS: ReadonlyArray<readonly [RegExp, string]> = [
  [startsWith(S.tabNodes), "nodes"],
  [startsWith(S.tabMetrics), "metrics"],
  [startsWith(S.tabValidation), "validation"],
  [startsWith(S.tabArtifacts), "artifacts"],
];

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    let target: Target | null = null;

    test.beforeAll(async ({ request }) => {
      target = await pickTarget(request);
    });

    test(`project home (${theme})`, async ({ page }) => {
      test.skip(target === null, "no project with nodes on this machine");
      const errs = watchErrors(page);
      await setTheme(page, theme);
      await page.goto(projectUrl(target!.project));
      await expect(page.getByText(S.heroTitle)).toBeVisible();
      await settle(page);
      await page.screenshot({ path: shotPath(`home-${theme}`) });
      expectNoErrors(errs);
    });

    test(`thread view, tabs, grow, supercell (${theme})`, async ({ page }) => {
      test.skip(target === null, "no project with nodes on this machine");
      const errs = watchErrors(page);
      await setTheme(page, theme);
      await page.goto(threadUrl(target!));
      const pane = page.locator("aside");
      await expect(pane.getByRole("button", { name: S.tabStructure, exact: true })).toBeVisible();
      // the 3Dmol canvas is the proof the viewer actually rendered
      await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
      await settle(page, 2500);
      await page.screenshot({ path: shotPath(`thread-structure-${theme}`) });

      for (const [label, file] of TABS) {
        await pane.getByRole("button", { name: label }).first().click();
        await settle(page, 1200);
        await page.screenshot({ path: shotPath(`thread-${file}-${theme}`) });
      }
      // R3.5: the 分析 tab computes the per-node product on first open
      // (canonical interactions + voids), so wait for the panel itself
      await pane.getByRole("button", { name: startsWith(S.tabAnalysis) }).first().click();
      await expect(page.getByTestId("analysis-panel")).toBeVisible({ timeout: 90_000 });
      // R4: the topology section rides in the same product
      const topo = page.getByTestId("analysis-topology");
      await expect(topo).toBeVisible();
      await settle(page, 1500);
      await page.screenshot({ path: shotPath(`thread-analysis-${theme}`) });
      // the tab scrolls: bring the 拓扑 section itself into the frame
      await topo.scrollIntoViewIfNeeded();
      await settle(page, 600);
      await page.screenshot({ path: shotPath(`thread-analysis-topology-${theme}`) });
      await pane.getByRole("button", { name: S.tabStructure, exact: true }).click();
      await settle(page, 800);

      // R1.2: the controls float on the canvas. ＋生长 is the one-press
      // action beside the extent menu; the slices live in the menu.
      const grow = pane.getByRole("button", { name: "＋" + S.growOnce });
      await expect(grow).toBeVisible();
      await grow.click();
      await settle(page, 2500);
      await grow.click();
      await settle(page, 2500);
      await page.screenshot({ path: shotPath(`thread-grow2-${theme}`) });

      const extentMenu = pane.locator('button[aria-haspopup="menu"]').first();
      await expect(extentMenu).toBeVisible();
      await extentMenu.click();
      await expect(pane.getByRole("menuitem", { name: startsWith(S.modeAsu) })).toBeVisible();
      await page.screenshot({ path: shotPath(`thread-extent-menu-${theme}`) });
      await pane.getByRole("menuitem", { name: new RegExp(rx(`${S.modeSuper} 2×2×2`)) }).click();
      await settle(page, 4000);
      await page.screenshot({ path: shotPath(`thread-supercell-${theme}`) });

      // R1.3: Olex2 pack r - a sphere of whole molecules around the ASU centroid
      await extentMenu.click();
      await pane.getByRole("menuitem", { name: startsWith(`${S.modeRadius} 8 Å`) }).click();
      await settle(page, 4000);
      await expect(extentMenu).toContainText(`${S.modeRadius} 8 Å`);
      await page.screenshot({ path: shotPath(`thread-radius8-${theme}`) });

      // the bottom bar: open the 绘制 panel and the 证据 panel
      await pane.getByRole("button", { name: startsWith(S.grpDraw) }).click();
      await settle(page, 600);
      await page.screenshot({ path: shotPath(`thread-panel-draw-${theme}`) });
      await pane.getByRole("button", { name: startsWith(S.grpEvidence) }).click();
      await settle(page, 600);
      await page.screenshot({ path: shotPath(`thread-panel-evidence-${theme}`) });
      // 孔道: the void surface + labels at the inscribed-sphere centres
      // (voids.json v3, D17) - built on first request, so wait generously
      await pane.getByRole("button", { name: S.ovVoids, exact: true }).click();
      await settle(page, 12000);
      await page.screenshot({ path: shotPath(`thread-voids-${theme}`) });
      await pane.getByRole("button", { name: S.ovVoids, exact: true }).click();
      await page.keyboard.press("Escape");

      // 关系: the interaction layer (R2.3) - turning a pill on re-fetches
      // the scene with interactions=1 and draws the engine's rows
      await pane.getByRole("button", { name: startsWith(S.grpRelations) }).click();
      await settle(page, 400);
      await pane.getByRole("button", { name: S.ovHbonds, exact: true }).click();
      await pane.getByRole("button", { name: "π–π", exact: true }).click();
      await pane.getByRole("button", { name: "C–H···X", exact: true }).click();
      await settle(page, 6000);
      await page.screenshot({ path: shotPath(`thread-panel-relations-${theme}`) });
      // R4: the simplified net (nodes + edges with lattice shifts) reads the
      // node's analysis product - already built by the 分析 tab above
      await pane.getByRole("button", { name: S.ovNet, exact: true }).click();
      await settle(page, 8000);
      await page.screenshot({ path: shotPath(`thread-net-${theme}`) });
      await pane.getByRole("button", { name: S.ovNet, exact: true }).click();
      await page.keyboard.press("Escape");

      // the structure card opens from the key bar
      await pane.locator(`button[title="${S.headerExpand}"]`).click();
      await settle(page, 600);
      await page.screenshot({ path: shotPath(`thread-header-open-${theme}`) });
      expectNoErrors(errs);
    });
  });
}
