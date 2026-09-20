/** Synthetic UI-only lifecycle fixtures. No model calls or scientific claims.
 * GETs read the chosen existing project; every write is intercepted locally.
 * Run against an isolated Vite preview (CP_BASE_URL) or the integrated UI. */
import { expect, test, type Page } from "@playwright/test";
import { shotPath, threadUrl, watchErrors } from "./helpers";
import { S, rx } from "./lang";

const project = process.env.CP_E2E_PROJECT;
const threadId = process.env.CP_SOL_THREAD;
const startTs = 1_700_000_000;
const tool = { server: "crystalpilot", tool: "run_shelxl", args: {}, status: "in_progress", duration_ms: null, ok: null, result_tail: null, error: null };
const initialEvents = [
  { kind: "user_message", text: "Synthetic UI lifecycle fixture - not a scientific run", ts: startTs },
  { kind: "turn_started", ts: startTs },
  { kind: "reasoning_summary", text: "Synthetic reasoning preview", ts: startTs + 1 },
  { kind: "tool_started", ...tool, ts: startTs + 2 },
];

async function fixture(page: Page, events: object[] = initialEvents, expectedState = "working", earlier: object[] = [], beforePage?: () => Promise<void>) {
  const threads = await page.request.get(`/api/threads/list?project=${encodeURIComponent(project!)}`);
  expect(threads.ok()).toBe(true);
  const list = await threads.json();
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.pathname === "/api/projects/open") {
      await route.fulfill({ json: { project, threads: list.threads ?? [] } });
    } else if (url.pathname === "/api/threads/transcript") {
      const older = url.searchParams.has("before");
      if (older) await beforePage?.();
      const rows = older ? earlier : events;
      await route.fulfill({ json: { events: rows, total: events.length + earlier.length, oldest_eid: older ? 1 : earlier.length + 1, has_more: !older && earlier.length > 0, live_cursor: 0, generation: "synthetic-ui" } });
    } else if (req.method() !== "GET") {
      await route.fulfill({ status: 409, json: { detail: "Synthetic read-only UI test blocks writes" } });
    } else {
      await route.continue();
    }
  });
  await page.addInitScript(() => {
    localStorage.setItem("cp.viewMode", "concise");
    const Native = window.EventSource;
    let emit: ((event: object) => void) | undefined;
    let seq = 0;
    class SyntheticEvents {
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      closed = false;
      constructor() {
        emit = (event) => { if (!this.closed) this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event), lastEventId: String(++seq) })); };
        setTimeout(() => { if (!this.closed) this.onopen?.(new Event("open")); }, 0);
      }
      close() { this.closed = true; }
    }
    window.EventSource = function (url: string | URL, options?: EventSourceInit) {
      return String(url).includes("/api/threads/events") ? new SyntheticEvents() : new Native(url, options);
    } as unknown as typeof EventSource;
    Object.defineProperty(window, "emitSynthetic", { value: (event: object) => emit?.(event) });
  });
  await page.goto(threadUrl({ project: project!, threadId: threadId! }) + "&view=structure");
  await expect(page.getByTestId("status-rail")).toHaveAttribute("data-state", expectedState);
}

async function emit(page: Page, event: object) {
  await page.evaluate((ev) => (window as unknown as { emitSynthetic: (event: object) => void }).emitSynthetic(ev), event);
}

async function visibility(page: Page, state: "hidden" | "visible") {
  // Deterministic visibility event simulation, not a real background-tab test.
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test.beforeEach(() => { test.skip(!project || !threadId, "requires CP_E2E_PROJECT and CP_SOL_THREAD for an existing read-only project"); });

test("real read-only transcript and renderer respect motion preferences", async ({ page }) => {
  const errors = watchErrors(page);
  const response = await page.request.get(`/api/threads/transcript?thread_id=${encodeURIComponent(threadId!)}&project=${encodeURIComponent(project!)}&limit=1000`);
  expect(response.ok()).toBe(true);
  const data = await response.json();
  expect(data.events.some((ev: { kind: string }) => ev.kind === "turn_completed")).toBe(true);
  await fixture(page, data.events, "idle");
  const canvas = page.locator("aside canvas").first();
  await expect(canvas).toBeVisible();
  await expect(page.locator('[data-testid="tool-row"][data-status="running"]')).toHaveCount(0);
  await page.screenshot({ path: shotPath("conversation-real-replay") });
  const frame = () => canvas.evaluate((el) => (el as HTMLCanvasElement).toDataURL());
  await page.getByRole("button", { name: S.grpView, exact: true }).click();
  await page.getByRole("button", { name: S.ovSpin, exact: true }).click();
  const spinning = await frame();
  await expect.poll(frame).not.toBe(spinning);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForTimeout(150);
  const still = await frame();
  await page.waitForTimeout(250);
  expect(await frame()).toBe(still);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect.poll(frame).not.toBe(still);
  await visibility(page, "hidden");
  await page.waitForTimeout(150);
  const hidden = await frame();
  await page.waitForTimeout(250);
  expect(await frame()).toBe(hidden);
  await visibility(page, "visible");
  await expect.poll(frame).not.toBe(hidden);
  await page.getByRole("button", { name: S.ovSpin, exact: true }).click();
  await visibility(page, "hidden");
  await visibility(page, "visible");
  await page.waitForTimeout(150);
  const off = await frame();
  await page.waitForTimeout(250);
  expect(await frame()).toBe(off);
  expect(errors.pageErrors).toEqual([]);
});

test("real 3Dmol depth survives centering cancelled before its first frame (Vite)", async ({ page }) => {
  // Access the already-loaded dependency's public prototype only to observe
  // the real viewer. This instrumentation requires Vite source serving.
  const source = await (await page.request.get("/src/workbench/crystal/CrystalViewer.tsx")).text();
  const moduleUrl = source.match(/from "([^"]*\/3dmol\.js[^"]*)"/)?.[1];
  test.skip(!moduleUrl, "requires a Vite CP_BASE_URL for real-viewer instrumentation");
  const errors = watchErrors(page);
  await fixture(page);
  const canvas = page.locator("aside canvas").first();
  await expect(canvas).toBeVisible();
  await page.evaluate(async (url) => {
    const imported = await import(/* @vite-ignore */ url);
    const mol = imported.default ?? imported;
    const original = mol.GLViewer.prototype.zoomTo;
    mol.GLViewer.prototype.zoomTo = function (...args: unknown[]) {
      (window as any).depthTestViewer = this;
      return original.apply(this, args);
    };
  }, moduleUrl!);
  await page.getByTitle(S.resetView, { exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as any).depthTestViewer))).toBe(true);
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const viewer = (window as any).depthTestViewer;
    const atom = viewer.getModel().selectedAtoms({}).find((candidate: any) => typeof candidate.callback === "function");
    if (!atom) throw new Error("No real selectable atom");
    atom.callback(atom, viewer);
  });
  await expect(page.getByRole("button", { name: S.selCenter, exact: true })).toBeVisible();
  const before = await page.evaluate(() => (window as any).depthTestViewer.getSlab());
  await page.evaluate(() => {
    const frames = new Map<number, FrameRequestCallback>();
    let seq = 0;
    window.requestAnimationFrame = (callback) => { frames.set(++seq, callback); return seq; };
    window.cancelAnimationFrame = (id) => { frames.delete(id); };
    (window as any).heldCenterFrames = frames;
  });
  await page.getByRole("button", { name: S.selCenter, exact: true }).evaluate((el) => (el as HTMLElement).click());
  await expect.poll(() => page.evaluate(() => (window as any).heldCenterFrames.size)).toBeGreaterThan(0);
  await canvas.dispatchEvent("pointerdown", { pointerId: 1, pointerType: "mouse", button: 0 });
  expect(await page.evaluate(() => (window as any).heldCenterFrames.size)).toBe(0);
  const after = await page.evaluate(() => {
    const viewer = (window as any).depthTestViewer;
    viewer.rotate(30, "y");
    viewer.render();
    return viewer.getSlab();
  });
  expect(after.near).toBeCloseTo(before.near, 8);
  expect(after.far).toBeCloseTo(before.far, 8);
  expect(errors.pageErrors).toEqual([]);
});

test("synthetic terminal rows retain focus, questions and explicit errors", async ({ page }) => {
  const errors = watchErrors(page);
  await fixture(page);
  const reasoning = page.getByRole("button", { name: new RegExp(rx(S.reasoningSummary)) }).first();
  await reasoning.click();
  await expect(reasoning).toBeFocused();
  await emit(page, { kind: "agent_message", ts: startTs + 3, text: '```ask\n{"question":"Synthetic prior question?"}\n```' });
  await emit(page, { kind: "user_steer", ts: startTs + 4, text: "Synthetic steer must stay visible" });
  await emit(page, { kind: "tool_completed", ...tool, tool: "inspect_model", status: "failed", ok: false, error: "Synthetic explicit failure", ts: startTs + 5 });
  await emit(page, { kind: "turn_completed", status: "interrupted", duration_ms: 6000, ts: startTs + 6 });
  await expect(page.getByTestId("status-rail")).toHaveAttribute("data-state", "interrupted");
  await expect(reasoning).toBeFocused();
  await expect(reasoning).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("tool-row").filter({ hasText: "Synthetic explicit failure" })).toBeVisible();
  await expect(page.locator('[data-testid="tool-row"][data-status="interrupted"]')).toBeVisible();
  await expect(page.locator('[data-testid="tool-row"][data-status="running"]')).toHaveCount(0);
  await expect(page.getByTestId("ask-card")).toBeVisible();
  await expect(page.getByText("Synthetic steer must stay visible")).toBeVisible();
  expect(errors.pageErrors).toEqual([]);
});

test("synthetic focused tool fold survives termination and view-mode changes", async ({ page }) => {
  await fixture(page);
  const row = page.getByTestId("tool-row").first();
  const summary = row.locator(":scope > summary");
  await summary.click();
  await emit(page, { kind: "turn_completed", status: "interrupted", duration_ms: 6000, ts: startTs + 6 });
  await expect(summary).toBeFocused();
  await expect(row).toHaveJSProperty("open", true);
  // Programmatic mode changes deliberately retain focus in the fold.
  await page.getByRole("button", { name: S.viewVerbose, exact: true }).evaluate((el) => (el as HTMLElement).click());
  await page.getByRole("button", { name: S.viewConcise, exact: true }).evaluate((el) => (el as HTMLElement).click());
  await expect(row).toHaveJSProperty("open", true);
  await row.locator(":scope > div > details > summary").click();
  await row.getByRole("button", { name: S.copyMessage, exact: true }).first().focus();
  await row.evaluate((el) => { (el as HTMLDetailsElement).open = false; });
  await expect(summary).toBeFocused();
});

test("synthetic motion preference and visibility pause one working indicator", async ({ page }) => {
  const now = Date.now() / 1000;
  await fixture(page, initialEvents.map((ev) => ({ ...ev, ts: now + ev.ts - startTs })));
  const rail = page.getByTestId("rail-action");
  await expect(page.locator(".pulse-star")).toHaveCount(1);
  await expect(page.locator('[data-testid="tool-row"] .shimmer-text')).toHaveCount(1);
  await expect(rail.locator(".shimmer-text")).toHaveCount(1);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".pulse-star")).toHaveCount(0);
  await expect(rail.locator(".shimmer-text")).toHaveCSS("animation-name", "none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(page.locator(".pulse-star")).toHaveCount(1);
  await visibility(page, "hidden");
  await expect(page.locator("html")).toHaveAttribute("data-page-hidden", "");
  const paused = await rail.innerText();
  await page.waitForTimeout(2200);
  expect(await rail.innerText()).toBe(paused);
  await visibility(page, "visible");
  await expect(page.locator("html")).not.toHaveAttribute("data-page-hidden");
  await expect(rail).not.toHaveText(paused);
});

test("synthetic pending history page cannot replace focused reasoning with a failed command", async ({ page }) => {
  const errors = watchErrors(page);
  const earlier = [
    { kind: "turn_started", ts: startTs - 4, eid: 1 },
    { kind: "command_completed", ts: startTs - 3, eid: 2, command: "synthetic failed command", status: "failed", exit_code: 2, output_tail: "Historical failure must remain visible" },
    { kind: "agent_message", ts: startTs - 2, eid: 3, text: "Earlier reply" },
    { kind: "turn_completed", ts: startTs - 1, eid: 4, status: "completed", duration_ms: 3000 },
  ];
  const tail = initialEvents.slice(1).map((ev, i) => ({ ...ev, eid: 5 + i }));
  let release = () => {};
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await fixture(page, tail, "working", earlier, () => pending);
  await page.getByTestId("load-earlier").click();
  await expect(page.getByTestId("load-earlier")).toBeDisabled();
  const reasoning = page.getByRole("button", { name: new RegExp(rx(S.reasoningSummary)) }).first();
  await reasoning.click();
  await expect(reasoning).toBeFocused();
  release();
  const failure = page.locator('[data-testid="command-row"][data-status="failed"]').first();
  await expect(failure.locator(":scope > summary")).toBeVisible();
  await expect(failure.locator(".activity-issue")).toBeVisible();
  await expect(reasoning).toBeFocused();
  await expect(reasoning).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("Synthetic reasoning preview", { exact: true })).toBeVisible();
  await failure.evaluate(el => { (el as HTMLDetailsElement).open = true; });
  await expect(page.getByText("Historical failure must remain visible", { exact: true }).first()).toBeVisible();
  await expect(reasoning).toBeFocused();
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors.filter((error) => /same key/i.test(error))).toEqual([]);
});

test("synthetic server paging preserves the visible source row after id renumbering", async ({ page }) => {
  const earlier = Array.from({ length: 80 }, (_, i) => ({ kind: "agent_message", text: `Synthetic earlier page ${i}`, ts: startTs - 160 + i, eid: i + 1 }));
  const tail = Array.from({ length: 80 }, (_, i) => ({ kind: "agent_message", text: `Synthetic tail page ${i}`, ts: startTs - 80 + i, eid: 81 + i }));
  const events = [...tail, ...initialEvents.map((ev, i) => ({ ...ev, eid: 161 + i }))];
  await fixture(page, events, "working", earlier);
  const scroll = page.getByTestId("message-scroll");
  await scroll.evaluate((el) => { el.scrollTop = 0; el.dispatchEvent(new Event("scroll")); });
  const first = scroll.locator('[data-chat-anchor]').filter({ hasText: "Synthetic tail page 0" }).first();
  const before = await first.evaluate((el) => el.getBoundingClientRect().top);
  await page.getByTestId("load-earlier").click();
  await expect(page.getByText("Synthetic earlier page 0", { exact: true })).toBeAttached();
  await expect.poll(() => first.evaluate((el) => el.getBoundingClientRect().top)).toBeCloseTo(before, 0);
  await expect(scroll.getByTestId("load-earlier")).toHaveCount(0);
});

test("synthetic history scroll stays anchored; reduced-motion jump is instant", async ({ page }) => {
  const history = Array.from({ length: 340 }, (_, i) => ({ kind: "agent_message", text: `Synthetic history paragraph ${i}`, ts: startTs - 350 + i }));
  await fixture(page, [...history, ...initialEvents]);
  const scroll = page.getByTestId("message-scroll");
  await scroll.evaluate((el) => { el.scrollTop = 120; el.dispatchEvent(new Event("scroll")); });
  const before = await scroll.evaluate((el) => el.scrollTop);
  await emit(page, { kind: "agent_message", ts: startTs + 7, text: "Synthetic appended message must not force scrolling" });
  expect(await scroll.evaluate((el) => el.scrollTop)).toBeCloseTo(before, 0);
  await scroll.getByRole("button", { name: new RegExp(rx(S.showEarlierPrefix)) }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await scroll.evaluate((el) => {
    const scrollTo = el.scrollTo.bind(el);
    el.scrollTo = ((options: ScrollToOptions) => { el.setAttribute("data-scroll-behavior", options.behavior ?? ""); scrollTo(options); }) as typeof el.scrollTo;
  });
  await page.getByTestId("jump-to-latest").click();
  await expect(scroll).toHaveAttribute("data-scroll-behavior", "auto");
  await expect.poll(() => scroll.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(2);
});
