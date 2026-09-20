/** Replay a completed REAL Sol diagnosis; never synthesize events or invoke a model. */
import { expect, test } from "@playwright/test";
import { setTheme, shotPath, threadUrl, watchErrors } from "./helpers";
import { S } from "./lang";

const PROJECT = process.env.CP_E2E_PROJECT;
const THREAD = process.env.CP_SOL_THREAD;
const TOOLS = ["get_project_brief", "inspect_model", "reflection_statistics", "get_geometry"];

for (const theme of ["light", "dark"] as const) {
  test(`real Sol diagnostic transcript and crystal (${theme})`, async ({ page, request }) => {
    test.skip(!PROJECT || !THREAD, "requires the completed real Sol audit thread");
    const response = await request.get(`/api/threads/transcript?thread_id=${encodeURIComponent(THREAD!)}&project=${encodeURIComponent(PROJECT!)}&limit=1000`);
    expect(response.ok()).toBe(true);
    const data = await response.json() as { events: { kind: string; tool?: string; ok?: boolean }[] };
    const completed = data.events.filter((e) => e.kind === "tool_completed").slice(0, 4);
    expect(completed.map((e) => e.tool)).toEqual(TOOLS);
    expect(completed.every((e) => e.ok)).toBe(true);
    const errors = watchErrors(page);
    await page.setViewportSize(theme === "light" ? { width: 1440, height: 900 } : { width: 1100, height: 800 });
    await setTheme(page, theme);
    await page.goto(threadUrl({ project: PROJECT!, threadId: THREAD! }) + "&view=structure");
    await expect(page.locator("aside canvas").first()).toBeVisible();
    await expect(page.getByTestId("model-button")).toContainText("Sol");
    await expect(page.getByTestId("model-button")).toContainText(S.effortLabels.xhigh);
    await expect(page.getByText(/目前没有重新精修/)).toBeVisible();
    await expect(page.getByTestId("status-rail")).toHaveAttribute("data-state", "idle");
    await page.screenshot({ path: shotPath(`sol-diagnostic-${theme}`) });
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}
