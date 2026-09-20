/** Real completed experiments only: no injected events, model calls or user answers. */
import { expect, test } from "@playwright/test";
import { shotPath, threadUrl, watchErrors } from "./helpers";
import { S, rx } from "./lang";

const CAGE = process.env.CP_CAGE_PROJECT;
const CAGE_THREAD = process.env.CP_CAGE_THREAD;
const SMALL = process.env.CP_SMALL_PROJECT;
const SMALL_THREAD = process.env.CP_SMALL_THREAD;
const REPORT = process.env.CP_SMALL_CHECKCIF_REPORT;

test("real Cage retains chemistry questions and coalesces startup across live answers", async ({ page, request }) => {
  test.skip(!CAGE || !CAGE_THREAD, "requires real Cage diagnostic thread");
  const params = new URLSearchParams({ project: CAGE!, thread_id: CAGE_THREAD!, limit: "1000" });
  const transcript = await (await request.get(`/api/threads/transcript?${params}`)).json();
  const startup = transcript.events.filter((e: { kind: string; server?: string }) => e.kind === "mcp_startup" && e.server === "crystalpilot");
  const ready = startup.filter((e: { status?: string }) => e.status === "ready");
  expect(ready.length).toBeGreaterThanOrEqual(2);
  expect(ready.every((e: { n_tools?: number }) => e.n_tools === undefined)).toBe(true);
  let readyCycles = 0;
  let previousStatus = "";
  for (const event of startup) {
    if (event.status === "ready" && previousStatus !== "ready") readyCycles += 1;
    previousStatus = event.status;
  }
  // The user may answer in the actual browser while this regression runs.
  const lastUser = transcript.events.findLastIndex((e: { kind: string }) => e.kind === "user_message");
  const lastAsk = transcript.events.findLastIndex((e: { kind: string; text?: string }) => e.kind === "agent_message" && e.text?.includes("```ask"));
  expect(lastAsk).toBeGreaterThanOrEqual(0);
  const pending = lastAsk > lastUser;
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(threadUrl({ project: CAGE!, threadId: CAGE_THREAD! }) + "&view=structure");
  const historicalQuestion = page.getByTestId("ask-card").filter({ hasText: "金属元素和主要配体" }).first();
  await historicalQuestion.scrollIntoViewIfNeeded();
  await expect(historicalQuestion).toBeVisible();
  if (pending) {
    await expect(page.getByTestId("ask-dock")).toBeVisible();
    await expect(page.getByTestId("status-rail")).toHaveAttribute("data-state", "question");
  } else {
    await expect(page.getByTestId("ask-dock")).toHaveCount(0);
    await expect(page.getByTestId("status-rail")).toHaveAttribute("data-state", "idle");
  }
  const readiness = page.getByText(new RegExp("^" + rx(S.sysMcpReady)));
  await expect(readiness).toHaveCount(readyCycles);
  await expect(readiness).not.toContainText("?");
  await expect(readiness).not.toContainText("？");
  await expect(page.getByTestId("model-button")).toContainText("Sol");
  await page.screenshot({ path: shotPath("cage-real-question-and-readiness") });
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});

test("real small-molecule checkCIF counts and node source agree with the sidebar", async ({ page, request }) => {
  test.skip(!SMALL || !SMALL_THREAD || !REPORT, "requires real refined small molecule and checkCIF artifact");
  const params = new URLSearchParams({ project: SMALL!, path: REPORT! });
  const response = await request.get(`/api/wb/artifact?${params}`);
  expect(response.ok()).toBe(true);
  const report = await response.json();
  expect(report.execution_status).toBe("completed");
  expect(report.report_status).toBe("complete");
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(threadUrl({ project: SMALL!, threadId: SMALL_THREAD! }) + "&view=structure");
  const pane = page.locator("aside");
  await expect(pane.locator("canvas").first()).toBeVisible();
  await pane.getByRole("button", { name: new RegExp("^" + rx(S.tabValidation)) }).first().click();
  await expect(pane.getByTestId("validation-origin")).toContainText(report.source.node);
  for (const level of ["A", "B", "C"]) {
    await expect(pane.getByText(`${level}×${report.counts[level]}`, { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: shotPath("small-real-checkcif-sidebar") });
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});
