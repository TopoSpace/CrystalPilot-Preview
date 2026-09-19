/** Read-only check of real UTF-8 project names through the API and browser. */
import { expect, test } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";

const PROJECT = process.env.CP_CIF_PROJECT;
const NAME = process.env.CP_PROJECT_DISPLAY_NAME;

test("real Chinese project name survives storage, API and display", async ({ page, request }) => {
  test.skip(!PROJECT || !NAME, "set CP_CIF_PROJECT and its CP_PROJECT_DISPLAY_NAME");
  const response = await request.get("/api/projects/recent");
  expect(response.ok()).toBe(true);
  const rows = await response.json() as { path: string; display_name: string | null }[];
  const normalize = (s: string) => s.replaceAll("\\", "/").toLowerCase();
  const row = rows.find((r) => normalize(r.path) === normalize(PROJECT!));
  expect(row?.display_name).toBe(NAME);
  expect(row?.display_name).not.toMatch(/\?{2,}|\uFFFD/);
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(projectUrl(PROJECT!));
  await expect(page.locator("main")).toContainText(NAME!);
  await page.screenshot({ path: shotPath("project-name-utf8") });
  expect(errors.pageErrors).toEqual([]);
});
