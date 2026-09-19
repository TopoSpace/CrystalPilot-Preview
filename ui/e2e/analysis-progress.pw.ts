import { expect, test } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";

const PROJECT = process.env.CP_CIF_PROJECT;

test("progressive transport keeps real completed blocks when a later block fails", async ({ page, request }) => {
  test.skip(!PROJECT, "set CP_CIF_PROJECT to a real CIF document");
  const source = await request.post("/api/wb/refine/analysis/jobs", { data: { project: PROJECT, node: "n0000" } });
  expect(source.ok()).toBe(true);
  let actual = await source.json();
  const actualObserver = actual.observer_id;
  await expect.poll(async () => {
    actual = await (await request.get(`/api/wb/refine/analysis/jobs/${actual.job_id}?project=${encodeURIComponent(PROJECT!)}`)).json();
    return actual.status;
  }, { timeout: 90_000 }).toMatch(/^(ready|partial)$/);
  expect(actual.result.interactions).not.toBeNull();
  await request.post(`/api/wb/refine/analysis/jobs/${actual.job_id}/release`,
    { data: { project: PROJECT, observer_id: actualObserver } });

  // Only delivery timing/failure is injected; the displayed successful blocks
  // come from the real computation above, not invented crystallographic values.
  let failPores = false;
  const jobId = "ui-transport-fixture";
  const snapshot = () => ({ ...actual, job_id: jobId, observer_id: "ui-observer-fixture",
    status: failPores ? "partial" : "running", revision: failPores ? 3 : 2,
    result_revision: failPores ? 3 : 2, cache_hit: false,
    stages: { ...actual.stages, pores: { status: failPores ? "error" : "running",
      elapsed_s: 2, error: failPores ? "Controlled transport-test pore failure" : null,
      note: failPores ? "受控测试：这一项没有计算结果" : "孔道仍在计算" } },
    result: { ...actual.result, pores: null },
  });
  await page.route((url) => url.pathname === "/api/wb/refine/analysis/jobs", (route) => route.fulfill({ json: snapshot() }));
  await page.route((url) => url.pathname === `/api/wb/refine/analysis/jobs/${jobId}`, (route) => {
    const response = snapshot();
    const since = new URL(route.request().url()).searchParams.get("since_result_revision");
    if (since === String(response.result_revision)) response.result = null;
    return route.fulfill({ json: response });
  });
  await page.route((url) => url.pathname === `/api/wb/refine/analysis/jobs/${jobId}/release`,
    (route) => route.fulfill({ json: { released: true } }));
  const errors = watchErrors(page);
  await page.goto(projectUrl(PROJECT!) + "&view=structure");
  await page.locator("aside").getByRole("button", { name: "分析", exact: true }).click();
  await expect(page.getByTestId("analysis-panel")).toBeVisible();
  await expect(page.locator('[data-stage="interactions"][data-status="ready"]')).toBeAttached();
  await expect(page.getByTestId("analysis-stage-pores")).toHaveAttribute("data-status", "running");
  await expect(page.locator("aside canvas").first()).toBeVisible();
  await page.waitForResponse((response) => new URL(response.url()).pathname === `/api/wb/refine/analysis/jobs/${jobId}`);
  await expect(page.locator('[data-stage="interactions"][data-status="ready"]')).toBeAttached();
  await page.screenshot({ path: shotPath("progressive-transport-fixture-running") });
  failPores = true;
  await expect(page.getByTestId("analysis-stage-pores")).toHaveAttribute("data-status", "error");
  await expect(page.locator('[data-stage="interactions"][data-status="ready"]')).toBeAttached();
  await expect(page.getByTestId("analysis-stage-pores")).not.toContainText("无溶剂可及孔道");
  await page.getByTestId("analysis-stage-pores").scrollIntoViewIfNeeded();
  await page.screenshot({ path: shotPath("progressive-transport-fixture-partial") });
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});
