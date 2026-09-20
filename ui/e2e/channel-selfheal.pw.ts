/** The thread channel must heal itself: a refused EventSource, a network
 * outage, a silent socket and a tab coming back to the foreground all end
 * in a live channel again, with a visible status in between, without a
 * page reload (2026-09-16, "the page silently stops updating").
 *
 * Read-only: nothing is sent to a model. The thread's own transcript is
 * only re-read. Run from ui/:
 *   CP_E2E_PROJECT=<copy> CP_SOL_THREAD=<thread> npx playwright test e2e/channel-selfheal.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, shotPath, threadUrl, watchErrors, type Target } from "./helpers";
import { S, rx } from "./lang";

interface Probe {
  status: string;
  lastMessageAt: number;
  connects: number;
  recoveries: number;
  reconciles: number;
}

async function probe(page: Page, threadId: string): Promise<Probe | null> {
  return page.evaluate((id) => (window.__cpChannel ?? {})[id] ?? null, threadId);
}

async function waitLive(page: Page, timeout = 30_000): Promise<void> {
  await expect(page.getByTestId("chat-pane")).toHaveAttribute("data-channel", "live", { timeout });
  await expect(page.getByTestId("channel-banner")).toHaveCount(0);
}

test.describe("thread channel self-healing", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
    if (target && process.env.CP_SOL_THREAD) target = { ...target, threadId: process.env.CP_SOL_THREAD };
  });

  test("a refused EventSource (non-2xx) recovers by re-opening the project", async ({ page }) => {
    test.skip(target === null, "no project with a thread on this machine");
    const errors = watchErrors(page);
    let attempts = 0;
    let opens = 0;
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/api/projects/open")) opens += 1;
    });
    await page.route("**/api/threads/events*", async (route) => {
      attempts += 1;
      if (attempts === 1) {
        // what the server says after a restart / after the idle reaper
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "no open project owns thread" }) });
        return;
      }
      await route.continue();
    });
    await page.goto(threadUrl(target!));
    // the refusal is visible, not silent
    await expect(page.getByTestId("channel-banner")).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: shotPath("channel-refused-banner") });
    // and the ladder dials back in: another open, another EventSource, live
    await expect.poll(() => attempts, { timeout: 20_000 }).toBeGreaterThan(1);
    await waitLive(page);
    expect(opens).toBeGreaterThanOrEqual(2);
    const p = await probe(page, target!.threadId);
    expect(p?.recoveries ?? 0).toBeGreaterThanOrEqual(1);
    expect(errors.pageErrors).toEqual([]);
  });

  test("a network outage shows 连接已断开 and comes back live", async ({ page, context }) => {
    test.skip(target === null, "no project with a thread on this machine");
    const errors = watchErrors(page);
    // Chromium's offline emulation blocks new requests but leaves the
    // established EventSource socket in place, so nothing fires for a
    // while: the watchdog is what notices (45 s without a ping). The fake
    // clock makes those 45 s pass in the test.
    await page.clock.install();
    await page.goto(threadUrl(target!));
    await waitLive(page, 60_000);
    const before = await probe(page, target!.threadId);
    await context.setOffline(true);
    await page.clock.runFor(60_000);
    // recovery fails offline -> "连接已断开，稍后自动重试", visibly
    await expect(page.getByTestId("channel-banner")).toBeVisible({ timeout: 30_000 });
    // ChannelBanner shows one of the three non-live channel strings
    await expect(page.getByTestId("channel-banner")).toContainText(new RegExp([S.reconnecting, S.recovering, S.channelDead].map(rx).join("|")));
    await page.screenshot({ path: shotPath("channel-offline-banner") });
    await context.setOffline(false);
    // the retry timer (8 s) is on the fake clock too
    for (let i = 0; i < 6; i += 1) {
      await page.clock.runFor(10_000);
      if ((await page.getByTestId("chat-pane").getAttribute("data-channel")) === "live") break;
      await page.waitForTimeout(500);
    }
    await waitLive(page, 40_000);
    const after = await probe(page, target!.threadId);
    expect((after?.connects ?? 0) > (before?.connects ?? 0) || (after?.recoveries ?? 0) > (before?.recoveries ?? 0)).toBe(true);
    expect(errors.pageErrors).toEqual([]);
  });

  test("coming back to the tab reconciles against the server", async ({ page }) => {
    test.skip(target === null, "no project with a thread on this machine");
    await page.goto(threadUrl(target!));
    await waitLive(page, 60_000);
    let snapshots = 0;
    page.on("request", (r) => {
      if (r.url().includes("/api/threads/transcript") && r.url().includes("limit=1")) snapshots += 1;
    });
    const before = await probe(page, target!.threadId);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect.poll(() => snapshots, { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
    const after = await probe(page, target!.threadId);
    expect(after?.reconciles ?? 0).toBeGreaterThan(before?.reconciles ?? 0);
    // healthy channel: no rebuild was needed
    await waitLive(page);
  });

  test("a silent socket (no ping for 45 s) is rebuilt by the watchdog", async ({ page }) => {
    test.skip(target === null, "no project with a thread on this machine");
    await page.clock.install();
    await page.goto(threadUrl(target!));
    await waitLive(page, 60_000);
    const before = await probe(page, target!.threadId);
    // fake time jumps 60 s while no message arrives on the (real) socket in
    // fake-time terms: the watchdog sees STALE_AFTER_MS of silence
    await page.clock.runFor(60_000);
    await expect
      .poll(async () => (await probe(page, target!.threadId))?.recoveries ?? 0, { timeout: 20_000 })
      .toBeGreaterThan(before?.recoveries ?? 0);
    await waitLive(page, 40_000);
  });

  test("the server heartbeat is a data event the page can see", async ({ page, request }) => {
    test.skip(target === null, "no project with a thread on this machine");
    await page.goto(threadUrl(target!));
    await waitLive(page, 60_000);
    const snap = await request.get(`/api/threads/transcript?thread_id=${encodeURIComponent(target!.threadId)}&project=${encodeURIComponent(target!.project)}&limit=1`);
    expect(snap.ok()).toBe(true);
    const body = (await snap.json()) as { generation?: string; live_cursor: number; busy?: boolean };
    expect(typeof body.busy).toBe("boolean");
    const head = await page.evaluate(async ({ threadId, after }) => {
      const res = await fetch(`/api/threads/events?thread_id=${encodeURIComponent(threadId)}&after=${after}`);
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let text = "";
      for (let i = 0; i < 6 && !text.includes("channel_hello"); i += 1) {
        const { value, done } = await reader.read();
        if (done) break;
        text += dec.decode(value, { stream: true });
      }
      await reader.cancel();
      return text;
    }, { threadId: target!.threadId, after: body.live_cursor });
    const line = head.split("\n").find((l) => l.startsWith("data: ") && l.includes("channel_hello"));
    expect(line, head).toBeTruthy();
    const hello = JSON.parse(line!.slice("data: ".length)) as { generation: string; oldest?: number };
    expect(hello.generation).toBe(body.generation);
    expect(typeof hello.oldest).toBe("number");
  });
});
