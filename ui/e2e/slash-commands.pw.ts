/** Every slash command, by mouse and by keyboard, must open the same thing.
 *
 * 2026-09-16 root cause: the palette executed the command inside its
 * `mousedown` handler; React 18 committed the state change synchronously,
 * the model / permission menu mounted and registered its document-level
 * "mousedown outside -> close" listener while the very same mousedown was
 * still bubbling, and the detached palette button counted as "outside", so
 * the menu closed in the tick it opened. Keyboard Enter has no mousedown and
 * always worked. Commands that open a note card or a dialog (keydown-only
 * dismissal) were unaffected, which matched the report "some commands work
 * when clicked".
 *
 * Side-effecting commands (compact / fork / rename / mcp / skills) are
 * intercepted at the network layer: nothing is sent to a model, no thread is
 * created or renamed. Run from ui/:
 *   CP_E2E_PROJECT=<copy> CP_SOL_THREAD=<thread> npx playwright test e2e/slash-commands.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, threadUrl, watchErrors, type Target } from "./helpers";
import { S, rx } from "./lang";

type Check = (page: Page, seen: Set<string>) => Promise<void>;

const visible = (testId: string): Check => async (page) => {
  await expect(page.getByTestId(testId)).toBeVisible({ timeout: 10_000 });
};
const noteWith = (text: string | RegExp): Check => async (page) => {
  const note = page.getByTestId("note-row").last();
  await expect(note).toBeVisible({ timeout: 10_000 });
  await expect(note).toContainText(text);
};
const requested = (marker: string): Check => async (_page, seen) => {
  await expect.poll(() => seen.has(marker), { timeout: 10_000, message: `no ${marker} request` }).toBe(true);
};

/** command -> what must appear afterwards */
const EXPECTATIONS: Array<{ name: string; check: Check; leavesThread?: boolean }> = [
  { name: "model", check: visible("model-menu") },
  { name: "effort", check: visible("model-menu") },
  { name: "permissions", check: visible("permission-menu") },
  { name: "subagents", check: visible("permission-menu") },
  { name: "compact", check: requested("compact") },
  { name: "context", check: noteWith(S.noteContextTitle) },
  { name: "status", check: noteWith(S.noteStatusTitle) },
  { name: "mcp", check: noteWith(S.noteMcpTitle) },
  { name: "skills", check: noteWith(new RegExp(rx(S.noteSkillsTitle) + "|skill", "i")) },
  { name: "rename", check: noteWith(/rename/) },
  { name: "settings", check: visible("settings-dialog") },
  { name: "stop", check: async (page) => { await expect(page.getByTestId("slash-palette")).toHaveCount(0); } },
  { name: "fork", check: requested("fork"), leavesThread: true },
  { name: "new", check: async (page) => { await expect(page).toHaveURL(/\/\?project=/, { timeout: 10_000 }); }, leavesThread: true },
];

async function closeAnyPopover(page: Page): Promise<void> {
  // Escape closes menus and the settings dialog; a second one is harmless
  await page.keyboard.press("Escape");
  await page.waitForTimeout(120);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(120);
  // dismiss any note card left behind so `.last()` is the fresh one
  for (const btn of await page.getByTestId("note-row").locator("button").all()) {
    await btn.click().catch(() => undefined);
  }
}

async function installMocks(page: Page, seen: Set<string>, target: Target): Promise<void> {
  await page.route("**/api/threads/compact", async (route) => {
    seen.add("compact");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, thread_id: target.threadId }) });
  });
  await page.route("**/api/threads/fork", async (route) => {
    seen.add("fork");
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ thread_id: target.threadId, task_id: "e2e", threads: [] }),
    });
  });
  await page.route("**/api/threads/rename", async (route) => {
    seen.add("rename");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ thread: {}, threads: [] }) });
  });
  await page.route("**/api/projects/mcp_status", async (route) => {
    seen.add("mcp");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ present: true, n_tools: 77, error: null }) });
  });
  await page.route("**/api/skills?*", async (route) => {
    seen.add("skills");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ skills: [{ name: "e2e-skill", description: "fixture", enabled: true }] }) });
  });
}

test.describe("slash commands: mouse and keyboard open the same thing", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
    if (target && process.env.CP_SOL_THREAD) target = { ...target, threadId: process.env.CP_SOL_THREAD };
  });

  for (const mode of ["click", "keyboard"] as const) {
    for (const { name, check, leavesThread } of EXPECTATIONS) {
      test(`/${name} by ${mode}`, async ({ page }) => {
        test.skip(target === null, "no project with a thread on this machine");
        const errors = watchErrors(page);
        const seen = new Set<string>();
        await installMocks(page, seen, target!);
        await page.goto(threadUrl(target!));
        const ta = page.getByTestId("composer").locator("textarea");
        await expect(ta).toBeVisible({ timeout: 60_000 });
        // wait for the transcript + live channel: that is the state a user
        // types in (a note issued before the first transcript landed used to
        // be discarded by the bootstrap; the reducer now keeps it, and this
        // spec is about the command dispatch, not that race)
        await expect(page.getByTestId("chat-pane")).toHaveAttribute("data-channel", "live", { timeout: 60_000 });
        await ta.click();
        await ta.fill(`/${name}`);
        await expect(page.getByTestId("slash-palette")).toBeVisible();
        const item = page.getByTestId(`slash-item-${name}`);
        await expect(item).toBeVisible();
        if (mode === "click") {
          await item.click();
        } else {
          // the first match is highlighted; Enter runs it (same path as Tab + Enter)
          await ta.press("Enter");
        }
        await check(page, seen);
        if (!leavesThread) {
          // the composer is still usable afterwards
          await expect(ta).toHaveValue("");
        }
        expect(errors.pageErrors, "uncaught page errors").toEqual([]);
        await closeAnyPopover(page);
      });
    }
  }

  test("a menu opened by click stays open until a real outside click", async ({ page }) => {
    test.skip(target === null, "no project with a thread on this machine");
    await page.goto(threadUrl(target!));
    const ta = page.getByTestId("composer").locator("textarea");
    await expect(ta).toBeVisible({ timeout: 60_000 });
    await ta.click();
    await ta.fill("/perm");
    await page.getByTestId("slash-item-permissions").click();
    const menu = page.getByTestId("permission-menu");
    await expect(menu).toBeVisible();
    // it survives a moment (the old bug closed it within the same event)
    await page.waitForTimeout(600);
    await expect(menu).toBeVisible();
    // and a genuine outside click closes it
    await page.mouse.click(10, 10);
    await expect(menu).toHaveCount(0);
  });
});
