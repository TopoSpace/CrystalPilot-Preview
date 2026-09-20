/** Real read-only inspector regression. No route mocks, model calls, checkout or settings saves.
 * CP_BASE_URL may point at a child Vite preview proxying the real 8010 service.
 * CP_E2E_PROJECT must contain a cached analysis with non-identity atom interactions (e.g. ZIF-8).
 */
import { expect, test, type Page } from "@playwright/test";
import type { AnalysisResponse, SceneResponse } from "../src/lib/wbTypes";
import { interactionLabel } from "../src/lib/interactions";
import { projectUrl, shotPath, watchErrors } from "./helpers";
import { S, rx } from "./lang";

const PROJECT = process.env.CP_E2E_PROJECT ?? "";
const params = () => `project=${encodeURIComponent(PROJECT)}`;

async function openAnalysis(page: Page, focus = true) {
  const errors = watchErrors(page);
  await page.goto(`${projectUrl(PROJECT)}&view=structure&tab=analysis${focus ? "&focus=1" : ""}`);
  await expect(page.getByTestId("analysis-panel")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("structure-viewport").locator("canvas").first()).toBeVisible();
  return errors;
}

async function range(page: Page, name: RegExp, mode: string) {
  const next = page.waitForResponse((r) => {
    const url = new URL(r.url());
    return r.ok() && url.pathname === "/api/wb/refine/scene" && url.searchParams.get("mode") === mode;
  });
  await page.locator('aside button[aria-haspopup="menu"]').first().click();
  await page.getByRole("menuitem", { name }).click();
  return await (await next).json() as SceneResponse;
}

test.beforeEach(async ({ page }) => {
  test.skip(!PROJECT, "Set CP_E2E_PROJECT to an authorized real external structure project");
  await page.addInitScript(() => {
    localStorage.setItem("cp.sect.header2", "0");
    localStorage.setItem("cp.sect.an.keep-structure", "1");
    localStorage.setItem("cp.sect.an.interactions", "1");
    localStorage.setItem("cp.analysis.structure-share", "55");
  });
});

test("real symmetry row selects its exact endpoint, quotes values and refuses an absent instance", async ({ page, request }) => {
  test.setTimeout(180_000);
  const nodes = await request.get(`/api/wb/refine/nodes?${params()}`);
  expect(nodes.ok()).toBe(true);
  const before = await nodes.json();
  const product = await request.get(`/api/wb/refine/analysis?${params()}&node=${before.active_node}`);
  expect(product.ok()).toBe(true);
  const data = await product.json() as AnalysisResponse;
  const canonical = Object.values(data.interactions?.unique ?? {}).flat()
    .find((r) => r && r.a && r.op.replace(/\s/g, "") !== "x,y,z");
  expect(canonical, "real project needs an atom interaction with non-identity symmetry").toBeTruthy();
  const row = canonical!;
  const errors = await openAnalysis(page);
  const extent = page.locator('aside button[aria-haspopup="menu"]').first();
  await extent.click();
  await page.getByRole("menu").press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(extent).toBeFocused();
  await expect(page.getByTestId("focus-toggle")).toHaveAttribute("aria-pressed", "true");
  await range(page, new RegExp("^" + rx(S.modeCell)), "cell");
  const panel = page.getByTestId("analysis-panel");
  const more = panel.getByRole("button", { name: new RegExp(rx(S.anMore)) });
  for (const button of await more.all()) await button.click();
  const item = panel.getByTestId("interaction-row")
    .filter({ has: page.getByRole("button", { name: S.crystal.locateAria(interactionLabel(row)), exact: true }) })
    .filter({ hasText: row.op }).first();
  const response = page.waitForResponse((r) => r.ok() && r.url().includes("/api/wb/refine/scene") && r.url().includes("interactions=1"));
  const locate = item.getByRole("button", { name: new RegExp("^" + rx(S.crystal.locateAria(""))) });
  await locate.focus();
  await locate.press("Enter");
  const scene = await (await response).json() as SceneResponse;
  const matches = scene.interactions!.rows.filter((r) => r.kind === row.kind && r.op === row.op && r.h === row.h && r.a === row.a);
  const displayed = matches.find((r) => !r.boundary && (r.bi !== null || r.ai !== null))
    ?? matches.find((r) => r.bi !== null || r.ai !== null);
  expect(displayed, "the real scene must contain the canonical interaction").toBeTruthy();
  const atom = scene.atoms[(displayed!.bi ?? displayed!.ai)!];
  expect(atom.sym).toBe(true);
  const inspector = page.getByTestId("analysis-inspector");
  await expect(inspector).toHaveAttribute("data-node", data.node);
  await expect(inspector).toHaveAttribute("data-match", "rendered");
  await expect(inspector).toHaveAttribute("data-atom-label", atom.label);
  await expect(inspector).toHaveAttribute("data-symop", atom.symop!);
  await expect(locate).toHaveAttribute("aria-pressed", "true");
  await item.getByRole("button", { name: S.anQuote, exact: true }).press("Space");
  await expect(page.locator("textarea").first()).toHaveValue(new RegExp(`\\[anchor node=${data.node}`));
  const draft = await page.locator("textarea").first().inputValue();
  expect(draft).toContain(`[anchor node=${data.node}`);
  expect(draft).toContain(row.op);
  if (typeof row.d_HA === "number") expect(draft).toContain(row.d_HA.toFixed(2));
  await page.screenshot({ path: shotPath("inspector-real-symmetry") });

  await range(page, new RegExp("^" + rx(S.modeAsu)), "asu");
  await expect(inspector).toHaveAttribute("data-match", "unavailable");
  await expect(inspector).toContainText(S.crystal.inspNoMatch);
  await expect(inspector).not.toHaveAttribute("data-atom-label");
  await expect(item).toContainText(row.op);
  const after = await (await request.get(`/api/wb/refine/nodes?${params()}`)).json();
  expect(after.active_node).toBe(before.active_node);
  expect(after.nodes.map((n: { id: string }) => n.id)).toEqual(before.nodes.map((n: { id: string }) => n.id));
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});

const layouts = [
  [390, 720, "kimi", "dark", 16],
  [900, 650, "anthropic", "light", 13],
  [1100, 700, "kimi", "light", 15],
  [1366, 768, "openai", "dark", 16],
  [1920, 1080, "openai", "light", 15],
  [1100, 700, "anthropic", "dark", 15],
] as const;

for (const [width, height, palette, theme, font] of layouts) {
  test(`inspector layout ${width}x${height} ${palette} ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(({ palette, theme, font }) => {
      localStorage.setItem("crystalpilot-palette", palette);
      localStorage.setItem("crystalpilot-theme", theme);
      localStorage.setItem("crystalpilot-font-size", String(font));
      localStorage.setItem("wb.rightPaneWidth", "300");
    }, { palette, theme, font });
    const errors = await openAnalysis(page, false);
    const viewport = page.getByTestId("structure-viewport");
    const oldHeight = (await viewport.boundingBox())!.height;
    expect(oldHeight).toBeGreaterThan(120);
    const slider = page.getByRole("slider", { name: S.crystal.paneStructureShareAria });
    await slider.focus();
    await slider.press("ArrowLeft");
    await expect(slider).toHaveValue("50");
    await expect.poll(async () => (await viewport.boundingBox())!.height).toBeLessThan(oldHeight);
    await page.getByTestId("analysis-panel").getByText(S.crystal.anCurrentCoordination, { exact: true }).click();
    const metal = page.getByRole("button", { name: new RegExp("^" + rx(S.crystal.coordLocateAria(""))) }).first();
    await expect(metal).toBeVisible();
    await metal.press("Space");
    await expect(metal).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("analysis-inspector")).toHaveAttribute("data-match", "atom");
    const header = page.getByTestId("identity-row1");
    const expand = header.locator("button[aria-expanded]");
    await header.getByRole("button", { name: S.headerQuote, exact: true }).press("Space");
    await expect(expand).toHaveAttribute("aria-expanded", "false");
    const node = (await header.innerText()).match(/\bn\d+\b/)?.[0];
    expect(node).toBeTruthy();
    await expect(page.getByTestId("anchor-rail")).toContainText(node!);
    await expand.press("Enter");
    await expect(expand).toHaveAttribute("aria-expanded", "true");
    expect(await page.locator("aside").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await header.locator("button button, button [role=button]").count()).toBe(0);
    await expand.press("Space");
    await page.screenshot({ path: shotPath(`inspector-${width}-${palette}-${theme}`) });
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}
