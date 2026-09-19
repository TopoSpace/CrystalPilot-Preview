/** Exercise the real workbench on completed Luna test projects, without
 * sending model messages or changing scientific inputs. */
import { expect, test, type Page } from "@playwright/test";
import { threadUrl, shotPath, watchErrors } from "./helpers";

const project = process.env.CP_E2E_PROJECT;
const threadId = process.env.CP_SOL_THREAD;
const tabs = ["结构", "分析", "节点树", "指标", "验证", "产物"];

async function open(page: Page) {
  await page.goto(threadUrl({ project: project!, threadId: threadId! }));
  await expect(page.locator('aside canvas').first()).toBeVisible({ timeout: 45_000 });
}
async function tab(page: Page, name: string) {
  await page.getByRole("group", { name: "结构工作区页面" }).getByRole("button", { name: new RegExp(`^${name}`) }).click();
}
async function settings(page: Page) {
  const opener = page.getByTestId("open-settings");
  if (!(await opener.isVisible())) await page.getByTestId("sidebar-expand").click();
  await opener.click();
  return page.getByTestId("settings-dialog");
}
test.beforeEach(async ({ page }) => {
  test.skip(!project || !threadId, "requires an existing completed Luna test case");
  await page.addInitScript(() => {
    localStorage.setItem("cp.viewMode", "concise");
    localStorage.setItem("wb.sidebarCollapsed", "0");
  });
});

test("all research panels show real data, with unchanged active scientific node", async ({ page, request }) => {
  test.setTimeout(120_000);
  const before = await (await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(project!)}`)).json();
  const errors = watchErrors(page);
  await open(page);
  for (const name of tabs) {
    await tab(page, name);
    await page.waitForTimeout(500);
    await expect(page.getByRole("group", { name: "结构工作区页面" }).getByRole("button", { name: new RegExp(`^${name}`) })).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: shotPath(`polished-${name}`) });
  }
  await tab(page, "指标");
  const metrics = page.getByTestId("metrics-panel");
  for (const label of ["R1", "wR2", "GooF"]) await expect(metrics.getByText(label, { exact: true }).first()).toBeVisible();
  await expect(metrics.locator(".metric-tile, .panel-heading")).toHaveCount(0);
  expect(await metrics.innerText()).not.toContain("NaN");
  await tab(page, "分析");
  await expect(page.getByTestId("analysis-panel")).toBeVisible();
  await page.getByRole("button", { name: "收起结构", exact: true }).click();
  await expect(page.getByRole("button", { name: "显示结构", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示结构", exact: true }).click();
  const after = await (await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(project!)}`)).json();
  expect(after.active_node).toBe(before.active_node);
  expect(errors.pageErrors).toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`settings sections, keyboard containment and menus (${theme})`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.addInitScript(value => localStorage.setItem("crystalpilot-theme", value), theme);
    await open(page);
    const dialog = await settings(page);
    for (const section of ["providers", "models", "context", "appearance", "advanced", "about"]) {
      await dialog.getByTestId(`settings-nav-${section}`).click();
      await expect(dialog.locator("h2")).not.toBeEmpty();
      await page.screenshot({ path: shotPath(`settings-polished-${section}-${theme}`) });
    }
    // Tab wraps at both boundaries without reaching the workbench behind it.
    const focusable = dialog.locator('button:visible, a[href]:visible, input:visible').filter({ visible: true });
    await focusable.last().focus();
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId("open-settings")).toBeFocused();
    await page.getByTestId("model-button").click();
    await expect(page.getByTestId("model-menu")).toBeVisible();
    await page.getByPlaceholder("搜索模型…").fill("luna");
    await expect(page.getByTestId("model-list")).toContainText(/luna/i);
    await page.screenshot({ path: shotPath(`model-polished-${theme}`) });
    await page.keyboard.press("Escape");
    await page.getByTestId("permission-chip").click();
    await expect(page.getByTestId("permission-menu")).toBeVisible();
    await page.screenshot({ path: shotPath(`permissions-polished-${theme}`) });
    await page.keyboard.press("Escape");
    const composer = page.locator("textarea").first();
    await composer.fill("/");
    await expect(page.getByTestId("slash-palette")).toBeVisible();
    await page.keyboard.press("Escape");
    await composer.fill("");
    expect(errors.pageErrors).toEqual([]);
  });
}

test("server folder browsing, CIF mode and dialog close work without a desktop picker", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "打开项目", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "打开项目", exact: true });
  expect(await dialog.evaluate(el => el.getBoundingClientRect().width)).toBe(page.viewportSize()!.width);
  await dialog.getByTestId("browse-folder").click();
  const browser = dialog.getByTestId("folder-browser");
  const choose = browser.getByRole("button", { name: "选择此文件夹" });
  await expect(choose).toBeEnabled();
  // Walk to the project from wherever the browser starts (the default
  // projects folder on the Linux host; a drive root or the dialog's current
  // path on Windows): up to a common ancestor, then down one segment at a
  // time through the filter. Paths compare slash- and case-insensitively.
  const norm = (s: string) => s.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const target = norm(project!);
  const shown = async () => norm((await browser.locator("span.font-mono").first().getAttribute("title")) ?? "");
  const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (let guard = 0; guard < 12 && !(target === (await shown()) || target.startsWith((await shown()) + "/")); guard += 1) {
    const up = browser.getByRole("button", { name: "上一级文件夹" });
    if (!(await up.isEnabled())) break;
    await up.click();
    await expect(choose).toBeEnabled();
  }
  for (const segment of target.slice((await shown()).length).split("/").filter(Boolean)) {
    await browser.getByLabel("筛选文件夹").fill(segment);
    await browser.getByRole("button", { name: new RegExp(`^${escape(segment)}$`, "i") }).click();
    await expect(choose).toBeEnabled();
  }
  expect(await shown()).toBe(target);
  await choose.click();
  expect(norm(await dialog.getByRole("textbox").first().inputValue())).toBe(target);
  await dialog.getByRole("button", { name: "仅查看 CIF", exact: true }).click();
  await expect(dialog.locator('input[type="file"]')).toBeVisible();
  await page.screenshot({ path: shotPath("open-project-polished") });
  await dialog.getByRole("button", { name: "关闭项目选择" }).click();
  await expect(dialog).toBeHidden();
});

test("structure control groups, clipping, rendering toggles and image export", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = watchErrors(page);
  await open(page);
  const bar = page.getByTestId("viewer-control-bar");
  for (const name of ["绘制", "关系", "证据", "视图"]) {
    await bar.getByRole("button", { name: new RegExp(`^${name}`) }).click();
    const panel = page.getByTestId("viewer-control-panel");
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    await page.screenshot({ path: shotPath(`controls-${name}`) });
    const toggles = panel.locator('button[aria-pressed]:not([disabled])');
    if (await toggles.count()) {
      const button = toggles.first();
      const original = await button.getAttribute("aria-pressed");
      await button.click();
      await expect(button).not.toHaveAttribute("aria-pressed", original!);
      await button.click();
    }
    const slider = panel.locator('input[type="range"]').first();
    if (await slider.count()) {
      const value = await slider.inputValue();
      await slider.focus(); await slider.press("ArrowLeft"); await slider.press("ArrowRight");
      await slider.fill(value);
    }
    await page.keyboard.press("Escape");
  }
  const extent = page.locator('aside button[aria-haspopup="menu"]').first();
  await extent.click(); await expect(page.getByRole("menu")).toBeVisible(); await page.keyboard.press("Escape");
  const exportButton = bar.getByRole("button", { name: /导出.*PNG|导出.*图/ });
  const download = page.waitForEvent("download");
  await exportButton.click();
  expect((await download).suggestedFilename()).toMatch(/\.png$/);
  expect(errors.pageErrors).toEqual([]);
});

test("phone settings and project dialog stay inside the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(threadUrl({ project: project!, threadId: threadId! }));
  const dialog = await settings(page);
  await dialog.getByTestId("settings-nav-models").click();
  const surface = dialog.locator(".settings-surface");
  const box = (await surface.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: shotPath("settings-polished-mobile") });
  await page.keyboard.press("Escape");
  if (!(await page.getByTestId("sidebar-collapse").isVisible())) await page.getByTestId("sidebar-expand").click();
  await page.getByRole("button", { name: "打开项目", exact: true }).first().click();
  const picker = page.getByRole("dialog", { name: "打开项目", exact: true });
  await picker.getByTestId("browse-folder").click();
  await expect(picker.getByTestId("folder-browser")).toBeVisible();
  expect(await picker.evaluate(el => el.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: shotPath("folder-browser-mobile") });
});

test("presentation branding persists, can be disabled, and copyright stays below the composer", async ({ page }) => {
  await open(page);
  let dialog = await settings(page);
  await dialog.getByTestId('settings-nav-appearance').click();
  const toggle = () => dialog.getByRole('switch', { name: '展示模式', exact: true });
  const name = () => dialog.getByRole('textbox', { name: '左上角显示名称', exact: true });
  await expect(toggle()).toHaveAttribute('aria-checked', 'false');
  await expect(name()).toBeDisabled();
  await toggle().click();
  await name().fill('TopoSpace · 晶体研究');
  await page.screenshot({ path: shotPath('presentation-settings') });
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('workbench-brand')).toHaveText('TopoSpace · 晶体研究');
  await expect(page.getByTestId('workbench-copyright')).toHaveText('© 2026 TopoSpace. All rights reserved.');
  const footer = (await page.getByTestId('workbench-copyright').boundingBox())!;
  const model = (await page.getByTestId('model-button').boundingBox())!;
  expect(model.y + model.height).toBeLessThanOrEqual(footer.y);
  const composer = (await page.getByTestId('composer').boundingBox())!;
  expect(footer.x + footer.width / 2).toBeCloseTo(composer.x + composer.width / 2, 0);
  await expect(page.getByTestId('composer').getByTestId('workbench-copyright')).toHaveCount(1);
  await expect(page.locator('footer')).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('workbench-brand')).toHaveText('TopoSpace · 晶体研究');
  await page.getByTestId('sidebar-collapse').click();
  await expect(page.getByTestId('workbench-copyright')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('workbench-copyright')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: shotPath('presentation-footer-mobile') });
  await page.setViewportSize({ width: 1600, height: 1000 });
  dialog = await settings(page);
  await dialog.getByTestId('settings-nav-appearance').click();
  await toggle().click();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('workbench-brand')).toHaveText('CrystalPilot');
  dialog = await settings(page);
  await dialog.getByTestId('settings-nav-appearance').click();
  await toggle().click();
  await expect(name()).toHaveValue('TopoSpace · 晶体研究');
  await name().fill('');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('workbench-brand')).toHaveText('CrystalPilot');
});

test("Linux delivery links open the actual artifact instead of the application shell", async ({ page, request }) => {
  await open(page);
  const link = page.locator('.agent-message a[href^="/api/wb/artifact?"]').filter({ hasText: "final.cif" }).last();
  // only a transcript whose agent prose links final.cif exercises this;
  // a fixture without such a message skips instead of failing
  await page.locator(".agent-message").last().waitFor({ state: "attached", timeout: 30_000 }).catch(() => undefined);
  test.skip((await link.count()) === 0, "this transcript has no agent message linking final.cif");
  await expect(link).toBeVisible();
  const response = await request.get((await link.getAttribute("href"))!);
  expect(response.ok()).toBe(true);
  const text = await response.text();
  expect(text).toMatch(/data_/);
  expect(text).not.toContain('<div id="root">');
});

test("CIF import keeps the chosen file while browsing for its destination", async ({ page, request }) => {
  await open(page);
  await page.getByRole("button", { name: "打开项目", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "打开项目", exact: true });
  await dialog.getByRole("button", { name: "仅查看 CIF", exact: true }).click();
  const file = dialog.locator('input[type="file"]');
  await file.setInputFiles("../benchmark/public/sucrose/ref_cif.cif");
  await dialog.getByTestId("browse-folder").click();
  await dialog.getByRole("button", { name: "返回路径输入", exact: true }).click();
  expect(await file.evaluate((el: HTMLInputElement) => el.files?.[0]?.name)).toBe("ref_cif.cif");
  const destination = project!.replace(/[^/]+$/, `ui-cif-browser-${Date.now()}`);
  await dialog.getByLabel("保存到新的结构项目", { exact: true }).fill(destination);
  await dialog.getByRole("button", { name: "导入查看", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 45_000 });
  await expect(page.locator('aside canvas').first()).toBeVisible({ timeout: 45_000 });
  const response = await request.post("/api/projects/settings", { data: { path: destination, settings: { model_override: "gpt-5.6-luna", subagents: "off" } } });
  expect(response.ok()).toBe(true);
  const nodes = await (await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(destination)}`)).json();
  expect(nodes.nodes[0].structure_only).toBe(true);
  await page.screenshot({ path: shotPath("cif-browser-import") });
});
