/** Real structure, palette, range and quote integration. No model calls or mocked data. */
import { expect, test } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";

const PROJECT = process.env.CP_CIF_PROJECT;
const CASES = [
  ["anthropic", "light", 1100, 700],
  ["anthropic", "dark", 1366, 768],
  ["openai", "light", 1920, 1080],
  ["openai", "dark", 900, 650],
  ["kimi", "light", 1366, 768],
  ["kimi", "dark", 1100, 700],
] as const;

for (const [palette, mode, width, height] of CASES) {
  test(`real crystal and quote ${palette} ${mode} ${width}x${height}`, async ({ page, request }) => {
    test.skip(!PROJECT, "requires a real external CP_CIF_PROJECT");
    const response = await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(PROJECT!)}`);
    expect(response.ok()).toBe(true);
    const nodes = await response.json();
    const node = nodes.nodes.find((n: { id: string }) => n.id === nodes.active_node);
    expect(node.structure_only).toBe(true);
    expect(node.r1).toBeNull();
    const errors = watchErrors(page);
    await page.setViewportSize({ width, height });
    await page.addInitScript(({ palette, mode }) => {
      localStorage.setItem("crystalpilot-palette", palette);
      localStorage.setItem("crystalpilot-theme", mode);
      localStorage.setItem("crystalpilot-font-size", "15");
    }, { palette, mode });
    await page.goto(projectUrl(PROJECT!) + "&view=structure&focus=1");
    const pane = page.locator("aside");
    await expect(pane.locator("canvas").first()).toBeVisible();
    await expect(pane.getByTestId("identity-row1")).toContainText(node.id);
    await pane.getByRole("button", { name: "引用", exact: true }).click();
    await expect(page.getByTestId("anchor-rail")).toContainText(node.id);
    await expect(page.locator("textarea").first()).toHaveValue(new RegExp(`\\[anchor node=${node.id}`));
    const extent = pane.locator('button[aria-haspopup="menu"]').first();
    await extent.click();
    await page.screenshot({ path: shotPath(`crystal-${palette}-${mode}-range`) });
    const nextScene = page.waitForResponse((r) => {
      const url = new URL(r.url());
      return r.ok() && url.pathname === "/api/wb/refine/scene"
        && url.searchParams.get("mode") === "supercell" && url.searchParams.get("n") === "2";
    });
    await pane.getByRole("menuitem", { name: /超胞 2×2×2/ }).click();
    const scene = await (await nextScene).json();
    expect(scene.atoms.length).toBeGreaterThan(node.n_atoms);
    expect(scene.range.n_tiles).toBeGreaterThanOrEqual(8);
    await expect(extent).toContainText("2×2×2");
    await expect(pane.getByTestId("identity-row2")).toContainText(String(scene.meta.n_atoms));
    await page.screenshot({ path: shotPath(`crystal-${palette}-${mode}-supercell`) });
    await pane.getByRole("button", { name: "视图", exact: true }).click();
    await expect(pane.getByRole("slider", { name: "前后裁切" })).toBeVisible();
    await page.screenshot({ path: shotPath(`crystal-${palette}-${mode}-view`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}
