/** The project feed must survive being refused once.
 *
 * 2026-09-07, found while restoring the server after it went deaf: an open
 * tab reconnects its EventSource within milliseconds of the server coming
 * back, and for the first seconds after a restart the server answers
 * `400 project not open; call /api/projects/open first`. EventSource retries
 * by itself only after a *network* drop - a non-2xx reply ends the stream for
 * good. The tab then keeps rendering but silently stops receiving settings,
 * approval, rename and busy-state pushes until someone reloads the page.
 *
 * This forces exactly that 400 on the first feed request and asserts the app
 * re-opens the project and dials back in. Read-only: nothing is sent to a
 * model, no setting is changed. Run from ui/:
 *   npx playwright test e2e/feed-reconnect.pw.ts */
import { expect, test } from "@playwright/test";
import { pickTarget, projectUrl, watchErrors, type Target } from "./helpers";

test.describe("project feed reconnect", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
  });

  test("a 400 on the feed does not end it", async ({ page }) => {
    test.skip(target === null, "no real project on the status board");
    test.setTimeout(120_000);
    const errors = watchErrors(page);

    let feedAttempts = 0;
    let opensAfterRefusal = 0;
    page.on("request", (r) => {
      if (feedAttempts >= 1 && r.method() === "POST" && r.url().includes("/api/projects/open")) {
        opensAfterRefusal += 1;
      }
    });
    await page.route("**/api/projects/feed*", async (route) => {
      feedAttempts += 1;
      if (feedAttempts === 1) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "project not open; call /api/projects/open first" }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(projectUrl((target as Target).project));
    await expect.poll(() => feedAttempts, { timeout: 20_000 }).toBeGreaterThanOrEqual(1);

    // the ladder: ~1 s backoff -> POST /api/projects/open -> new EventSource
    await expect
      .poll(() => feedAttempts, { timeout: 30_000, message: "the feed never retried" })
      .toBeGreaterThan(1);
    expect(opensAfterRefusal).toBeGreaterThan(0);

    // and the app is still usable, not stuck on an error screen
    await expect(page.getByTestId("model-button")).toBeVisible({ timeout: 20_000 });
    expect(errors.pageErrors).toEqual([]);
  });
});
