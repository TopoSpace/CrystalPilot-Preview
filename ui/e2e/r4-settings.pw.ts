/** 2026-09-07 front-end sync evidence: the model button + its menu (provider
 * tabs, model list from the connected API, the model's own effort rungs),
 * the slimmed permission popover (tooltips, the ONE sub-agent switch), the
 * "/" command palette with keyboard navigation, the settings dialog
 * (providers & keys, context, advanced/kernel), the sidebar thread rename
 * affordance, the open-project dialog's 浏览… button, and the project-home
 * "新对话将创建在" hint. Read-only against the REAL server: nothing is sent
 * to a model, no key is typed, no setting is changed (the sub-agent switch
 * is toggled on and back off on the demo project only, which owns no
 * running engine). Screenshots land in workdir/ui-evidence/<round>/. Run:
 *   CP_EVIDENCE_ROUND=fe-0907 CP_E2E_PROJECT=<path> npx playwright test e2e/r4-settings.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, projectUrl, setTheme, shotPath, THEMES, threadUrl, watchErrors, type Target } from "./helpers";
import { S, rx } from "./lang";

async function settle(page: Page, ms = 700): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

const DEMO = process.env.CP_E2E_PROJECT ?? "H:\\CrystalPilot\\workbench\\demo-project";
/** The /status note's model line, `statusModel(model, provider)` with the
 * two values unknown to the test. */
const STATUS_MODEL_LINE = new RegExp(
  rx(S.shell.statusModel("__MODEL__", "__PROVIDER__")).replace("__MODEL__", ".+").replace("__PROVIDER__", ".+"),
);
/** Either automatic sub-agent state line (on at the top tier / off). */
const SUBAGENTS_AUTO_STATE = new RegExp(`${rx(S.subagentsStateAutoOn)}|${rx(S.subagentsStateAutoOff)}`);

for (const theme of THEMES) {
  test.describe(`front-end sync 2026-09-07 (${theme})`, () => {
    test("project home: model menu, permission menu, slash palette, settings, dialogs", async ({ page }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width: 1440, height: 900 });
      await setTheme(page, theme);
      const errors = watchErrors(page);
      await page.goto(projectUrl(DEMO));
      await settle(page, 1200);

      // the composer: permission chip, slash hint, model button
      await expect(page.getByTestId("permission-chip")).toBeVisible();
      await expect(page.getByTestId("model-button")).toBeVisible();
      await expect(page.getByTestId("new-thread-target")).toContainText(S.newThreadIn);
      await page.screenshot({ path: shotPath(`home-${theme}`) });

      // model menu: provider tabs, list from the API, effort rungs
      await page.getByTestId("model-button").click();
      const menu = page.getByTestId("model-menu");
      await expect(menu).toBeVisible();
      await expect(page.getByTestId("model-list").locator("button").first()).toBeVisible({ timeout: 30_000 });
      const rungs = await page.getByTestId("effort-picker").locator("[role=radio]").count();
      expect(rungs).toBeGreaterThan(1);
      await page.screenshot({ path: shotPath(`model-menu-${theme}`) });
      // the other provider tab reads its own list (OpenRouter: hundreds of ids)
      const tabs = menu.locator(":scope > div").first().locator("button");
      if ((await tabs.count()) > 2) {
        await tabs.nth(1).click();
        await page.waitForTimeout(1500);
        await page.screenshot({ path: shotPath(`model-menu-provider2-${theme}`) });
      }
      await page.keyboard.press("Escape");
      await expect(menu).toBeHidden();

      // permission menu: four modes with tooltips, the single sub-agent switch
      await page.getByTestId("permission-chip").click();
      const perm = page.getByTestId("permission-menu");
      await expect(perm).toBeVisible();
      await expect(perm.getByTestId("settings-subagents")).toContainText(S.subagentsSwitch);
      const tips = await perm.locator("[title]").evaluateAll((els) => els.map((e) => e.getAttribute("title") ?? ""));
      expect(tips.some((t) => t.includes(S.subagentsTip))).toBe(true);
      await page.screenshot({ path: shotPath(`permission-menu-${theme}`) });
      // toggle on -> the server records "on" and the state line follows; then back to auto
      const sw = perm.getByTestId("settings-subagents").getByRole("switch");
      const before = await sw.getAttribute("aria-checked");
      await sw.click();
      await expect(perm.getByTestId("subagents-state")).toContainText(before === "true" ? S.subagentsStateOff : S.subagentsStateOn, { timeout: 30_000 });
      await page.screenshot({ path: shotPath(`permission-menu-toggled-${theme}`) });
      await perm.getByTestId("settings-subagents").getByRole("button", { name: S.subagentsAutoLabel }).click();
      await expect(perm.getByTestId("subagents-state")).toContainText(SUBAGENTS_AUTO_STATE, { timeout: 30_000 });
      await page.keyboard.press("Escape");

      // slash palette: "/" lists the commands; arrows move; Tab completes
      const ta = page.locator("textarea");
      await ta.click();
      await ta.type("/");
      const pal = page.getByTestId("slash-palette");
      await expect(pal).toBeVisible();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      await expect(pal.locator("[aria-selected=true]")).toContainText("/permissions");
      await page.screenshot({ path: shotPath(`slash-palette-${theme}`) });
      await page.keyboard.press("Tab");
      await expect(ta).toHaveValue("/permissions");
      await page.keyboard.press("Escape");
      await ta.fill("");
      // /status writes a local note (no thread yet -> the composer's own card)
      await ta.type("/status");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("note-row")).toContainText(STATUS_MODEL_LINE);
      await page.screenshot({ path: shotPath(`slash-status-note-${theme}`) });

      // settings dialog: providers (no key ever shown), context, advanced/kernel
      await page.getByTestId("open-settings").click();
      const dlg = page.getByTestId("settings-dialog");
      await expect(dlg).toBeVisible();
      // the list shows each provider's authentication state, never the key itself
      await expect(dlg.getByTestId("provider-list")).toContainText(S.providerAuthMode);
      const bodyText = await dlg.innerText();
      expect(bodyText).not.toMatch(/sk-[A-Za-z0-9]{10,}/);
      await page.screenshot({ path: shotPath(`settings-providers-${theme}`) });
      await dlg.getByTestId("provider-add").click();
      await expect(dlg.getByTestId("provider-form")).toBeVisible();
      await page.screenshot({ path: shotPath(`settings-provider-form-${theme}`) });
      await dlg.getByTestId("settings-nav-context").click();
      await expect(dlg).toContainText(S.ctxAutoCompact);
      await page.screenshot({ path: shotPath(`settings-context-${theme}`) });
      await dlg.getByTestId("settings-nav-advanced").click();
      await expect(dlg.getByTestId("kernel-info")).toContainText("codex");
      await page.screenshot({ path: shotPath(`settings-advanced-${theme}`) });
      await page.keyboard.press("Escape");
      await expect(dlg).toBeHidden();

      // open-project dialog: the OS folder picker button exists (not clicked:
      // it would open a native dialog on the server desktop)
      await page.getByRole("button", { name: S.openProject }).first().click();
      await expect(page.getByTestId("browse-folder")).toBeVisible();
      await page.screenshot({ path: shotPath(`open-project-dialog-${theme}`) });
      await page.keyboard.press("Escape");

      // sidebar: rename affordance on thread rows (hover)
      const row = page.getByTestId("thread-row").first();
      if (await row.count()) {
        await row.hover();
        await expect(page.getByRole("button", { name: S.renameThread }).first()).toBeVisible();
      }

      expect(errors.pageErrors).toEqual([]);
      expect(errors.consoleErrors).toEqual([]);
    });
  });
}

test.describe("thread view: context meter, /status card, thread switching", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
  });

  test("context ring + note card + sidebar switch", async ({ page }) => {
    test.skip(target === null, "no real project with a node tree");
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await setTheme(page, "light");
    const errors = watchErrors(page);
    await page.goto(threadUrl(target as Target));
    await settle(page, 2500);
    // the composer's context meter shows once usage is known
    const meter = page.getByTestId("context-meter");
    if (await meter.count()) {
      await meter.hover();
      await page.waitForTimeout(400);
      await page.screenshot({ path: shotPath("thread-context-tooltip") });
    }
    // /status in a thread lands as a transcript card
    const ta = page.locator("textarea");
    await ta.click();
    await ta.type("/status");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("note-row").last()).toContainText(STATUS_MODEL_LINE, { timeout: 15_000 });
    await page.screenshot({ path: shotPath("thread-status-card") });

    // switching threads by clicking the sidebar rows must land on the clicked
    // thread (the report of a "stuck on a bad link" switch); each row twice
    const rows = page.getByTestId("thread-row");
    const n = Math.min(await rows.count(), 3);
    for (let i = 0; i < n; i++) {
      await rows.nth(i).click();
      await page.waitForTimeout(1500);
      const url = page.url();
      expect(url).toContain("/thread/");
      const live = await page.locator("[data-testid=rail-action]").innerText().catch(() => "");
      expect(live).not.toContain("连接失败");
    }
    await page.screenshot({ path: shotPath("thread-after-switching") });
    expect(errors.pageErrors).toEqual([]);
  });
});

/** The 2026-09-07 report: from a conversation of project A, clicking project
 * B in the sidebar killed the crystal pane with 3Dmol's
 * "transferToImageBitmap: Failed to create ImageBitmap from OffscreenCanvas"
 * (one OffscreenCanvas is shared by every viewer on the page, and the viewer
 * being torn down leaves it 0x0). A folder click now folds/unfolds that
 * project's conversations in place, and switching projects - which does
 * remount the viewer - must not take the pane down. */
test.describe("sidebar: folders fold, switching projects keeps the pane", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
  });

  test("folder folds in place; opening another project's thread does not crash the viewer", async ({ page }) => {
    test.skip(target === null, "no real project with a node tree");
    test.setTimeout(240_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await setTheme(page, "light");
    const errors = watchErrors(page);
    await page.goto(threadUrl(target as Target));
    await settle(page, 3000);

    // pin the right pane open: this is the state that keeps the 3Dmol viewer
    // mounted across the project switch (and the state the report came from)
    const collapse = page.getByTitle(S.collapse, { exact: true });
    if (await collapse.count()) {
      await collapse.first().click();
      await page.getByTitle(S.expand, { exact: true }).first().click();
      await settle(page, 2000);
    }

    const nav = page.locator("nav");
    const other = nav.getByRole("button", { name: "demo-project", exact: true });
    test.skip((await other.count()) === 0, "demo-project is not in the recent list");

    // clicking the folder unfolds it WITHOUT leaving the current thread
    const urlBefore = page.url();
    await other.first().click();
    await settle(page, 1500);
    expect(page.url()).toBe(urlBefore);
    const threads = nav.getByTestId("thread-row");
    await expect(threads.first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: shotPath("sidebar-folder-expanded") });

    // opening one of its conversations switches project and remounts the
    // viewer; the pane must survive
    const before = await threads.count();
    await threads.last().click();
    await settle(page, 6000);
    expect(page.url()).not.toBe(urlBefore);
    await expect(page.getByTestId("error-boundary-crystal")).toHaveCount(0);
    expect(before).toBeGreaterThan(0);
    await page.screenshot({ path: shotPath("sidebar-after-project-switch") });

    // and back into a project that actually has a structure
    await page.goto(threadUrl(target as Target));
    await settle(page, 6000);
    await expect(page.getByTestId("error-boundary-crystal")).toHaveCount(0);

    expect(errors.pageErrors).toEqual([]);
  });
});
