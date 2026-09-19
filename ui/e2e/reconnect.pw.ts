/** Round-3 R1 evidence: reload / reconnect on a REAL long thread.
 *
 * - every human input (user_message / user_steer in the transcript) is in
 *   the DOM exactly once after a reload, and again after paging every
 *   older transcript page in with "加载更早的记录";
 * - the SSE channel opens with a channel_hello carrying the generation
 *   token the transcript snapshot reported;
 * - the browser diagnostics sink accepts a report.
 *
 * Point CP_E2E_PROJECT at a project with a long thread (the 2026-09-05
 * live demo has 10 000+ transcript lines); otherwise the newest project
 * with nodes is used and the paging part is skipped when the transcript
 * fits in one page. Run:
 *   CP_EVIDENCE_ROUND=r3-r1 CP_E2E_PROJECT=<path> npx playwright test e2e/reconnect.pw.ts */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { pickTarget, shotPath, threadUrl, watchErrors, type Target } from "./helpers";

interface TranscriptPage {
  events: Array<{ kind: string; text?: string; eid?: number }>;
  total?: number;
  oldest_eid?: number | null;
  has_more?: boolean;
  live_cursor: number;
  generation?: string | null;
}

async function transcriptPage(
  request: APIRequestContext,
  t: Target,
  before?: number,
): Promise<TranscriptPage> {
  const qs = new URLSearchParams({ thread_id: t.threadId, project: t.project, limit: "2000" });
  if (before !== undefined) qs.set("before", String(before));
  const r = await request.get(`/api/threads/transcript?${qs.toString()}`);
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()) as TranscriptPage;
}

/** Every human input in the whole transcript, oldest first. */
async function allHumanInputs(request: APIRequestContext, t: Target): Promise<string[]> {
  const texts: string[] = [];
  let page = await transcriptPage(request, t);
  for (let guard = 0; guard < 50; guard += 1) {
    const here = page.events
      .filter((e) => e.kind === "user_message" || e.kind === "user_steer")
      .map((e) => e.text ?? "");
    texts.unshift(...here);
    if (!page.has_more || !page.oldest_eid) break;
    page = await transcriptPage(request, t, page.oldest_eid);
  }
  return texts;
}

async function bubbleTexts(page: Page): Promise<string[]> {
  return page.locator("[data-testid=user-bubble]").allInnerTexts();
}

async function loadEverything(page: Page): Promise<number> {
  let clicks = 0;
  for (let i = 0; i < 40; i += 1) {
    const earlier = page.getByText(/^显示更早的 /);
    const server = page.getByTestId("load-earlier");
    if (await earlier.isVisible().catch(() => false)) {
      await earlier.click();
      clicks += 1;
      await page.waitForTimeout(300);
      continue;
    }
    if (await server.isVisible().catch(() => false)) {
      await server.click();
      clicks += 1;
      // the button either turns back into its idle label or disappears
      // (last page) or is replaced by the in-memory "显示更早" button
      await expect
        .poll(
          async () => {
            const vis = await server.isVisible().catch(() => false);
            return vis ? await server.innerText() : "gone";
          },
          { timeout: 30_000 },
        )
        .not.toMatch(/正在加载/);
      await page.waitForTimeout(300);
      continue;
    }
    break;
  }
  return clicks;
}

function norm(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/** The bubble shows the text plus a 插话 tag and attachment chips; compare
 * by "transcript text is contained in bubble text". */
function matches(bubbles: string[], inputs: string[]): boolean {
  if (bubbles.length !== inputs.length) return false;
  const pool = bubbles.map(norm);
  for (const inp of inputs.map(norm)) {
    const i = pool.findIndex((b) => b.includes(inp.slice(0, 60)));
    if (i < 0) return false;
    pool.splice(i, 1);
  }
  return true;
}

test.describe("reload / reconnect (round-3 R1)", () => {
  let target: Target | null = null;
  let inputs: string[] = [];
  let total = 0;

  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
    if (target) {
      inputs = await allHumanInputs(request, target);
      total = (await transcriptPage(request, target)).total ?? 0;
    }
  });

  test("human inputs survive a reload exactly once, with and without paging", async ({ page, request }) => {
    test.skip(target === null, "no project with a thread on this machine");
    test.skip(inputs.length === 0, "thread has no human input yet");
    const errs = watchErrors(page);
    await page.goto(threadUrl(target!));
    await expect(page.locator("[data-testid=user-bubble]").first()).toBeVisible({ timeout: 60_000 });
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: shotPath("reconnect-first-load") });

    // what one page can show: the newest transcript page's inputs
    const firstPage = await transcriptPage(request, target!);
    const lastPageInputs = firstPage.events
      .filter((e) => e.kind === "user_message" || e.kind === "user_steer")
      .map((e) => e.text ?? "");
    const before = await bubbleTexts(page);
    expect(matches(before, lastPageInputs), `bubbles ${before.length} vs page inputs ${lastPageInputs.length}`).toBe(true);

    // page everything in, then every input of the whole transcript is there once
    const clicks = await loadEverything(page);
    test.info().annotations.push({ type: "load_clicks", description: String(clicks) });
    test.info().annotations.push({ type: "transcript_total", description: String(total) });
    const all = await bubbleTexts(page);
    expect(matches(all, inputs), `bubbles ${all.length} vs transcript inputs ${inputs.length}`).toBe(true);
    await page.screenshot({ path: shotPath("reconnect-all-pages") });

    // reload: same picture again, nothing doubled
    await page.reload();
    await expect(page.locator("[data-testid=user-bubble]").first()).toBeVisible({ timeout: 60_000 });
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await page.waitForTimeout(1500);
    const again = await bubbleTexts(page);
    expect(matches(again, lastPageInputs)).toBe(true);
    await loadEverything(page);
    const againAll = await bubbleTexts(page);
    expect(matches(againAll, inputs)).toBe(true);
    await page.screenshot({ path: shotPath("reconnect-after-reload") });

    expect(errs.pageErrors, "uncaught page errors").toEqual([]);
    expect(errs.consoleErrors, "console errors").toEqual([]);
  });

  test("the live channel opens with a channel_hello matching the transcript generation", async ({ page, request }) => {
    test.skip(target === null, "no project with a thread on this machine");
    await page.goto(threadUrl(target!));
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const snap = await transcriptPage(request, target!);
    expect(snap.generation, "project open -> generation known").toBeTruthy();
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
    }, { threadId: target!.threadId, after: snap.live_cursor });
    expect(head).toContain("retry: 2000");
    const line = head.split("\n").find((l) => l.startsWith("data: ") && l.includes("channel_hello"));
    expect(line, head).toBeTruthy();
    const hello = JSON.parse(line!.slice("data: ".length)) as { generation: string; seq: number };
    expect(hello.generation).toBe(snap.generation);
    expect(hello.seq).toBeGreaterThanOrEqual(snap.live_cursor);
  });

  test("the diagnostics sink accepts a browser report", async ({ request }) => {
    const r = await request.post("/api/ui/diagnostics", {
      data: { area: "e2e", message: "smoke", context: { threadId: "e2e" }, ts: Date.now() / 1000, url: "e2e" },
    });
    expect(r.ok(), await r.text()).toBe(true);
    expect((await r.json()).ok).toBe(true);
  });
});
