import { expect, test, type Page } from "@playwright/test";
import { pickTarget, shotPath, threadUrl, watchErrors, type Target } from "./helpers";

// Controlled event fixtures test React transitions, not crystallographic results.
const REPORT = { alerts: [{ code: "PLAT029", level: "A", text: "Lifecycle regression fixture" }],
  counts: { A: 1, B: 0, C: 0, G: 0 }, target: "test-only.cif" };

type TestWindow = Window & { __cpValidationEvent?: (event: object) => void };

async function controlledChannel(page: Page, artifact: boolean, report: object = REPORT): Promise<void> {
  await page.route((url) => url.pathname === "/api/threads/transcript", (route) =>
    route.fulfill({ json: { events: [], live_cursor: 0 } }));
  await page.route((url) => url.pathname === "/api/threads/artifacts", (route) =>
    route.fulfill({ json: artifact ? [{ path: "test-only-checkcif.json", rel: "checkcif.json", size: 1 }] : [] }));
  await page.route((url) => url.pathname === "/api/wb/artifact", (route) =>
    route.fulfill({ json: report }));
  await page.addInitScript(() => {
    const Native = window.EventSource;
    let seq = 0;
    class Controlled extends EventTarget {
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      readyState = 1;
      constructor(url: string | URL, config?: EventSourceInit) {
        super();
        if (!String(url).includes("/api/threads/events")) return new Native(url, config);
        (window as TestWindow).__cpValidationEvent = (event) => {
          this.onmessage?.(new MessageEvent("message", {
            data: JSON.stringify(event), lastEventId: String(++seq),
          }));
        };
        setTimeout(() => this.onopen?.(new Event("open")), 0);
      }
      close() { this.readyState = 2; }
    }
    window.EventSource = Controlled as unknown as typeof EventSource;
  });
}

async function emit(page: Page, kind: string, ok: boolean | null, tail: object | null): Promise<void> {
  await page.evaluate(({ kind, ok, tail }) => {
    (window as TestWindow).__cpValidationEvent?.({ kind, ts: Date.now() / 1000,
      server: "crystalpilot", tool: "run_checkcif", args: {},
      status: kind === "tool_started" ? "in_progress" : ok === false ? "failed" : "completed",
      duration_ms: kind === "tool_started" ? null : 100, ok,
      result_tail: tail === null ? null : JSON.stringify(tail),
      error: ok === false ? "Deliberate lifecycle regression failure" : null });
  }, { kind, ok, tail });
}

test.describe("checkCIF lifecycle (event fixtures)", () => {
  let target: Target | null = null;
  test.beforeAll(async ({ request }) => { target = await pickTarget(request); });

  test("artifact polling waits for project readiness", async ({ page }) => {
    test.skip(target === null, "no real workbench project");
    let ready = false;
    const premature: string[] = [];
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === "/api/projects/open" && response.ok()) ready = true;
    });
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/threads/artifacts" && !ready) {
        premature.push("artifacts requested before project/thread registration");
      }
    });
    await page.route((url) => url.pathname === "/api/projects/open", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.continue();
    });
    const artifacts = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/threads/artifacts" && response.ok());
    await page.goto(threadUrl(target!));
    await artifacts;
    expect(premature).toEqual([]);
  });

  test("durable timeout artifact shows failure provenance, not a clean report", async ({ page }) => {
    test.skip(target === null, "no real workbench project");
    await controlledChannel(page, true, {
      execution_status: "timeout", report_status: "partial", counts: null, alerts: [],
      error: "Synthetic PLATON timeout with durable diagnostics",
      source: { kind: "delivery", target: "test-only.cif", node: "n0002", revision: 3, delivery_revision: 4 },
    });
    await page.goto(threadUrl(target!));
    const pane = page.locator("aside");
    await pane.getByRole("button", { name: /^验证/ }).first().click();
    await expect(pane.getByText("checkCIF 运行失败", { exact: true })).toBeVisible();
    await expect(pane.getByText(/Synthetic PLATON timeout/)).toBeVisible();
    await expect(pane.getByTestId("validation-origin")).toContainText("n0002");
    await expect(pane.getByText(/A×0|B×0|C×0|G×0/)).toHaveCount(0);
    await page.screenshot({ path: shotPath("validation-synthetic-timeout-artifact") });
  });

  for (const artifact of [false, true]) {
    test(`${artifact ? "artifact fallback" : "empty panel"} to live check to failure`, async ({ page }) => {
      test.skip(target === null, "no real workbench project");
      await controlledChannel(page, artifact);
      const errors = watchErrors(page);
      await page.goto(threadUrl(target!));
      const pane = page.locator("aside");
      await pane.getByRole("button", { name: /^验证/ }).first().click();
      await expect.poll(() => page.evaluate(() => Boolean((window as TestWindow).__cpValidationEvent))).toBe(true);
      if (artifact) await expect(pane.getByText("Lifecycle regression fixture", { exact: true })).toBeVisible();
      else await expect(pane.getByText("还没有 checkCIF 结果", { exact: true })).toBeVisible();

      await emit(page, "tool_started", null, null);
      await expect(pane.getByText("正在运行 checkCIF…", { exact: true })).toBeVisible();
      await expect(pane.getByText("Lifecycle regression fixture", { exact: true })).toHaveCount(0);
      await emit(page, "tool_completed", true, { ok: true, summary: REPORT });
      await expect(pane.getByText("Lifecycle regression fixture", { exact: true })).toBeVisible();
      await emit(page, "tool_started", null, null);
      await emit(page, "tool_completed", false, { ok: false, error: "test failure" });
      await expect(pane.getByText("checkCIF 运行失败", { exact: true })).toBeVisible();
      await expect(pane.getByText("Lifecycle regression fixture", { exact: true })).toHaveCount(0);

      await emit(page, "tool_started", null, null);
      await emit(page, "tool_completed", true, {});
      await expect(pane.getByText("总数未知", { exact: true })).toBeVisible();
      await expect(pane.getByText(/A×0|B×0|C×0|G×0/)).toHaveCount(0);
      await page.screenshot({ path: shotPath(`validation-event-fixture-${artifact ? "artifact" : "empty"}`) });
      expect(errors.pageErrors).toEqual([]);
    });
  }
});
