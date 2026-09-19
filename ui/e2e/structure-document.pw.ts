import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { projectUrl, setTheme, shotPath, watchErrors, THEMES } from "./helpers";

const PROJECT = process.env.CP_CIF_PROJECT;
const ROOT = process.env.CP_CIF_PROJECT_ROOT;
const CIF = path.resolve("..", "benchmark", "data_ext2", "org_hsl_cod2241460", "ref.cif");

for (const theme of THEMES) {
  test(`real structure-only CIF (${theme})`, async ({ page, request }) => {
    test.skip(!PROJECT, "set CP_CIF_PROJECT to a real CIF-only project");
    const response = await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(PROJECT!)}`);
    expect(response.ok()).toBe(true);
    const nodes = await response.json();
    const node = nodes.nodes.find((n: { id: string }) => n.id === nodes.active_node);
    expect(node.structure_only).toBe(true);
    expect(node.r1).toBeNull();
    expect(node.metrics_current).toBe(false);
    const errors = watchErrors(page);
    const forbidden: string[] = [];
    page.on("request", (r) => {
      if (/\/api\/wb\/refine\/(map|peaks|data)\?/.test(r.url())) forbidden.push(r.url());
    });
    await page.setViewportSize(theme === "dark" ? { width: 1100, height: 700 } : { width: 1366, height: 900 });
    await setTheme(page, theme);
    await page.goto(projectUrl(PROJECT!) + "&view=structure");
    const pane = page.locator("aside");
    await expect(page.getByTestId("structure-only-notice")).toBeVisible();
    await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
    await pane.getByRole("button", { name: /^证据/ }).click();
    await expect(pane.getByRole("button", { name: "密度图", exact: true })).toBeDisabled();
    await expect(pane.getByRole("button", { name: "Q峰", exact: true })).toBeDisabled();
    await expect(pane.getByRole("button", { name: "孔道", exact: true })).toBeEnabled();
    await page.screenshot({ path: shotPath(`cif-evidence-${theme}`) });
    await page.keyboard.press("Escape");
    await pane.locator('button[aria-haspopup="menu"]').first().click();
    await pane.getByRole("menuitem", { name: /超胞 2×2×2/ }).click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: shotPath(`cif-supercell-${theme}`) });
    await pane.getByRole("button", { name: "分析", exact: true }).click();
    await expect(page.getByTestId("analysis-panel")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("analysis-progress")).toBeVisible();
    await expect(pane.locator("canvas").first()).toBeVisible();
    await expect(page.locator('[data-stage="interactions"][data-status="ready"]')).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: shotPath(`cif-progressive-${theme}`) });
    await expect(page.locator('[data-stage="pores"][data-status="ready"]')).toBeAttached({ timeout: 90_000 });
    await page.getByRole("button", { name: "分析时保留结构视图" }).click();
    await page.screenshot({ path: shotPath(`cif-analysis-${theme}`) });
    expect(forbidden).toEqual([]);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}

test("import a real CIF using the actual dialog", async ({ page }) => {
  test.skip(!ROOT || !fs.existsSync(CIF), "requires an external project root and real CIF fixture");
  const project = path.join(ROOT!, `ui-import-${Date.now()}`);
  await page.goto("/");
  await page.getByRole("button", { name: "打开项目", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "仅查看 CIF", exact: true }).click();
  await dialog.locator('input[type="file"]').setInputFiles(CIF);
  await dialog.getByRole("textbox", { name: "保存到新的结构项目", exact: true }).fill(project);
  await dialog.getByRole("button", { name: "导入查看", exact: true }).click();
  await expect(dialog).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByTestId("structure-only-notice")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("aside canvas").first()).toBeVisible();
  await page.screenshot({ path: shotPath("cif-import-dialog-result") });
});
