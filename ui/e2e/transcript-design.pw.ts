/** UI-only fixtures use the real renderer and read-only structure project.
 * Model turns and all project writes are intercepted; no scientific claims. */
import { expect, test, type Page } from "@playwright/test";
import { threadUrl, shotPath, watchErrors } from "./helpers";
import { S, rx } from "./lang";

const project = process.env.CP_E2E_PROJECT;
const threadId = process.env.CP_SOL_THREAD;
const ts = 1_800_000_000;
const call = (tool: string, summary: object, i: number) => ({
  kind: "tool_completed", server: "crystalpilot", tool, args: {}, status: "completed",
  ok: true, duration_ms: 12345, error: null, result_tail: JSON.stringify({ ok: true, summary }), ts: ts + i,
});
const completed = [
  { kind: "user_message", text: "界面验收样本：请检查模型与数据，保留影响判断的结果。", ts },
  { kind: "turn_started", ts },
  { kind: "agent_message", text: "我会先读取文件，再检查结构与精修结果。", ts: ts + 1 },
  { kind: "reasoning_summary", text: "界面样本的思考摘要", ts: ts + 2 },
  { kind: "command_completed", command: "cat specimen.cif", item_id: "cmd-one", status: "completed", exit_code: 0, output_tail: "data_specimen\n_cell_length_a 10", duration_ms: 98765, ts: ts + 3 },
  { kind: "command_completed", command: "rg CELL specimen.res", item_id: "cmd-two", status: "completed", exit_code: 0, output_tail: "CELL 0.71073 10 11 12 90 90 90", ts: ts + 4 },
  call("read_skill", { text: "只读说明" }, 5),
  { kind: "agent_message", text: "下面保留模型、精修与校验的关键记录。", ts: ts + 6 },
  call("inspect_model", { n_atoms: 45, space_group: "P 21", suspects: [], isolated_atoms: [] }, 7),
  call("run_shelxt", { adopted: true, space_group: "P 21", n_atoms: 45 }, 7.1),
  { kind: "approval_request", approval_id: "shelxl-approval", method: "mcp", detail: {}, ts: ts + 7.2 },
  { kind: "approval_decision", approval_id: "shelxl-approval", decision: "accept", auto: true, ts: ts + 7.3 },
  { ...call("run_shelxl", { shelxl: { r1_strong: 0.0412, wr2: 0.1099, goof: 0.969 } }, 7.4), args: { mode: "adopt" } },
  call("refine", { mode: "anisotropic", r1_strong: 0.0412, wr2: 0.1099, goof: 0.969, node: "n0001" }, 8),
  call("run_checkcif", { counts: { A: 0, B: 0, C: 1, G: 18 } }, 9),
  { kind: "command_completed", command: "cat absent-note.txt", item_id: "cmd-failed", status: "failed", exit_code: 1, output_tail: "Optional note is unavailable", ts: ts + 10 },
  { kind: "agent_message", text: "展示验证完成。以上数值仅用于界面样本，不是新的科研结论。", ts: ts + 11 },
  { kind: "turn_completed", status: "completed", duration_ms: 30000, ts: ts + 12 },
];

async function fixture(page: Page, events: object[] = completed) {
  const response = await page.request.get(`/api/threads/list?project=${encodeURIComponent(project!)}`);
  const list = await response.json();
  await page.route("**/api/**", async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/projects/open") await route.fulfill({ json: { project, threads: list.threads ?? [] } });
    else if (pathname === "/api/threads/transcript") await route.fulfill({ json: {
      events: events.map((e, i) => ({ ...e, eid: i + 1 })), total: events.length,
      oldest_eid: 1, has_more: false, live_cursor: 0, generation: "design-fixture",
    } });
    else if (request.method() !== "GET") await route.fulfill({ status: 409, json: { detail: "UI fixture blocks writes" } });
    else await route.continue();
  });
  await page.addInitScript(() => {
    localStorage.setItem("cp.viewMode", "concise");
    localStorage.setItem("wb.sidebarCollapsed", "0");
    const Native = window.EventSource;
    let emit: ((e: object) => void) | undefined;
    let seq = 100;
    class Events {
      onopen: ((e: Event) => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      closed = false;
      constructor() {
        emit = e => { if (!this.closed) this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(e), lastEventId: String(++seq) })); };
        setTimeout(() => this.onopen?.(new Event("open")), 0);
      }
      close() { this.closed = true; }
    }
    window.EventSource = function(url: string | URL, options?: EventSourceInit) {
      return String(url).includes("/api/threads/events") ? new Events() : new Native(url, options);
    } as unknown as typeof EventSource;
    Object.defineProperty(window, "emitDesign", { value: (e: object) => emit?.(e) });
    Object.defineProperty(navigator.clipboard, "writeText", { value: async (text: string) => {
      Object.defineProperty(window, "designClipboard", { value: text, configurable: true });
    } });
  });
  await page.goto(threadUrl({ project: project!, threadId: threadId! }));
  await expect(page.getByTestId("message-scroll")).toBeVisible();
  await expect(page.getByTestId("user-bubble").first()).toBeVisible();
}

test.beforeEach(() => { test.skip(!project || !threadId, "requires existing read-only project/thread"); });

test("streamed prose fades only new text, keeps its animation age and has no caret", async ({ page }) => {
  const errors = watchErrors(page);
  await fixture(page, [completed[0], completed[1]]);
  await page.getByTestId('right-collapse').click();
  const observed = await page.evaluate(async time => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    emit({ kind: "agent_delta", delta: "我会先读取衍射数据，", ts: time + 1 });
    for (let i = 0; i < 60 && !document.querySelector('.stream-fragment'); i++) await frame();
    const first = document.querySelector<HTMLElement>('.stream-fragment')!;
    const animation = first.getAnimations()[0];
    const born = performance.now();
    const opacity = Number(getComputedStyle(first).opacity);
    const age = Math.max(0, -parseFloat(first.style.animationDelay));
    emit({ kind: "agent_delta", delta: "再检查晶胞与空间群。", ts: time + 2 });
    await frame(); await frame();
    return {
      opacity, sameAnimation: animation === first.getAnimations()[0],
      connected: first.isConnected,
      text: document.querySelector('.agent-message .md')?.textContent,
      containerOpacity: getComputedStyle(document.querySelector('.agent-message .md')!).opacity,
      caret: document.querySelector('.agent-message .md > span[aria-hidden="true"]') !== null,
      age: performance.now() - born + age,
      animatedText: [...document.querySelectorAll('.stream-fragment')].map(el => el.textContent).join(''),
    };
  }, ts);
  expect(observed.opacity).toBeGreaterThanOrEqual(0.25);
  expect(observed.opacity).toBeLessThan(1);
  if (observed.connected) expect(observed.sameAnimation).toBe(true);
  else {
    // A slow software-rendered browser may settle the fade between frames.
    // In that case the prefix must already be native text, never replayed.
    expect(observed.age).toBeGreaterThanOrEqual(320);
    expect(observed.animatedText).not.toContain('我会先读取');
  }
  expect("我会先读取衍射数据，再检查晶胞与空间群。".startsWith(observed.text ?? "")).toBe(true);
  expect(observed.containerOpacity).toBe("1");
  expect(observed.caret).toBe(false);
  await expect(page.getByTestId('agent-message').locator('.md')).toHaveText('我会先读取衍射数据，再检查晶胞与空间群。');
  await expect(page.locator('.stream-fragment')).toHaveCount(0);

  // Formatting that closes in a later delta must not replay the old prefix.
  await page.evaluate(time => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit({ kind: "agent_delta", delta: "\n\n**精修", ts: time + 3 });
  }, ts);
  await expect(page.getByTestId('agent-message')).toContainText('精修');
  await page.evaluate(time => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit({ kind: "agent_delta", delta: "完成**，见 [报告](https://example.com)。\n\n| R1 | wR2 |\n| --- | --- |\n| 0.04 | 0.10 |\n\n```text\nR1 = 0.04\n```", ts: time + 4 });
  }, ts);
  const message = page.getByTestId('agent-message');
  await expect(message.locator('strong')).toHaveText('精修完成');
  await expect(message.getByRole('link', { name: '报告' })).toHaveAttribute('href', 'https://example.com');
  await expect(message.locator('table')).toContainText('0.04');
  await expect(message.locator('pre code')).toHaveText('R1 = 0.04\n');
  await expect(message.locator('pre .stream-fragment')).toHaveCount(0);
  await page.evaluate(time => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit({ kind: "agent_message", text: "已核对；最终数值以原始报告为准。", ts: time + 5 });
    emit({ kind: "turn_completed", status: "completed", duration_ms: 6000, ts: time + 6 });
  }, ts);
  await expect(message.locator('.md')).toHaveText('已核对；最终数值以原始报告为准。');
  await expect(message.locator('.stream-fragment')).toHaveCount(0);
  await expect(page.getByTestId('assistant-copy')).toHaveCount(1);
  expect(errors.pageErrors).toEqual([]);
});

test("stream fade respects reduced motion and background updates without catch-up replay", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixture(page, [completed[0], completed[1]]);
  await page.evaluate(time => (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'agent_delta', delta: '低动效模式立即显示。', ts: time + 1 }), ts);
  await expect(page.getByTestId('agent-message')).toContainText('低动效模式立即显示。');
  await expect(page.locator('.stream-fragment')).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(page.locator('.stream-fragment')).toHaveCount(0);
  await page.evaluate(time => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'agent_delta', delta: '后台收到的内容。', ts: time + 2 });
  }, ts);
  await expect(page.getByTestId('agent-message')).toContainText('后台收到的内容。');
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.locator('.stream-fragment')).toHaveCount(0);
  await page.evaluate(time => (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'turn_completed', status: 'interrupted', duration_ms: 3000, ts: time + 3 }), ts);
  await expect(page.getByTestId('agent-message')).toHaveAttribute('data-streaming', 'false');
  await expect(page.getByTestId('agent-message').locator('.md')).toHaveText('低动效模式立即显示。后台收到的内容。');
});

test("long streaming prose follows the tail but preserves a reader's scroll position", async ({ page }) => {
  const history = Array.from({ length: 45 }, (_, i) => ({ kind: 'agent_message', text: `历史段落 ${i}：核对模型、数据及验证记录。`, ts: ts + i }));
  await fixture(page, [completed[0], ...history, { kind: 'turn_started', ts: ts + 50 }]);
  const scroll = page.getByTestId('message-scroll');
  await page.evaluate(time => (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'agent_delta', delta: '新增研究记录。'.repeat(30), ts: time + 51 }), ts);
  await expect(page.locator('[data-streaming="true"]')).toContainText('新增研究记录');
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(3);
  await scroll.evaluate(el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); });
  await page.evaluate(time => (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'agent_delta', delta: '新的精修结果。'.repeat(10), ts: time + 52 }), ts);
  await expect(page.locator('[data-streaming="true"]')).toContainText('新的精修结果');
  expect(await scroll.evaluate(el => el.scrollTop)).toBe(0);
  await expect(page.getByTestId('jump-to-latest')).toBeVisible();
  await page.getByTestId('jump-to-latest').click();
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(3);
});

test("uneven upstream bursts play during silence and completion preserves the queued tail", async ({ page }) => {
  await fixture(page, [completed[0], completed[1]]);
  await page.getByTestId('right-collapse').click();
  const first = '晶体研究记录。'.repeat(20);
  const last = first + '后续完整结果。'.repeat(12);
  await page.evaluate(({ text, time }) => (window as unknown as { emitDesign: (e: object) => void }).emitDesign({ kind: 'agent_delta', delta: text, ts: time + 1 }), { text: first, time: ts });
  const row = page.getByTestId('agent-message');
  await expect(row).toHaveAttribute('data-presenting', 'true');
  await expect.poll(async () => Number(await row.getAttribute('data-visible-length'))).toBeGreaterThan(0);
  const beforeSilence = Number(await row.getAttribute('data-visible-length'));
  await page.waitForTimeout(650); // no model packets during this interval
  const afterSilence = Number(await row.getAttribute('data-visible-length'));
  expect(afterSilence - beforeSilence).toBeGreaterThan(15);
  expect(afterSilence - beforeSilence).toBeLessThan(55);
  expect(afterSilence).toBeLessThan(first.length);
  await row.evaluate(el => { (window as any).playbackOriginalRow = el; });
  await page.evaluate(({ delta, text, time }) => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit({ kind: 'agent_delta', delta, ts: time + 2 });
    emit({ kind: 'agent_message', text, eid: 700, ts: time + 3 });
    emit({ kind: 'turn_completed', status: 'completed', ts: time + 4, duration_ms: 4000 });
  }, { delta: last.slice(first.length), text: last, time: ts });
  await expect(row).toHaveAttribute('data-streaming', 'false');
  await expect(row).toHaveAttribute('data-presenting', 'true');
  expect(await row.evaluate(el => el === (window as any).playbackOriginalRow)).toBe(true);
  expect(Number(await row.getAttribute('data-visible-length'))).toBeLessThan(last.length);
  await expect(page.getByTestId('assistant-copy')).toHaveCount(0);
  await expect(page.getByTestId('turn-status')).toHaveCount(0);
  await expect(row).toHaveAttribute('data-presenting', 'false');
  await expect(row.locator('.md')).toHaveText(last);
  await expect(page.getByTestId('assistant-copy')).toHaveCount(1);
  await expect(page.getByTestId('turn-status')).toHaveAttribute('data-status', 'completed');
  await expect(row.locator('.stream-fragment')).toHaveCount(0);
});

test("a complete live message in a single packet still plays, and interruption does not flush", async ({ page }) => {
  await fixture(page, [completed[0], completed[1]]);
  await page.getByTestId('right-collapse').click();
  const text = '缓冲中的完整说明。'.repeat(10);
  await page.evaluate(({ text, time }) => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit({ kind: 'agent_delta', delta: text, ts: time + 1 });
    emit({ kind: 'turn_completed', status: 'interrupted', ts: time + 2, duration_ms: 2000 });
  }, { text, time: ts });
  const row = page.getByTestId('agent-message');
  await expect(row).toHaveAttribute('data-streaming', 'false');
  await expect(row).toHaveAttribute('data-presenting', 'true');
  await expect(row).toHaveAttribute('data-presenting', 'false');
  await expect(row.locator('.md')).toHaveText(text);
  await expect(page.getByTestId('assistant-copy')).toHaveCount(0);
});

test("scientific successes stay visible, auxiliary work folds, arrows follow text and copy actions match message roles", async ({ page }) => {
  const errors = watchErrors(page);
  await fixture(page);
  for (const tool of ["inspect_model", "refine", "run_checkcif"]) {
    await expect(page.locator(`[data-tool="${tool}"] > summary`)).toBeVisible();
  }
  await expect(page.getByText(S.toolCards.suspectAtoms(0), { exact: false }).first()).toBeVisible();
  const summary = page.locator('[data-tool="inspect_model"] > summary');
  // Scientific icons describe the operation, with compact consecutive rows.
  const solve = page.locator('[data-tool="run_shelxt"]');
  const refine = page.locator('[data-tool="run_shelxl"]');
  await expect(solve.locator(':scope > summary [data-activity-icon="solve"]')).toBeVisible();
  await expect(refine.locator(':scope > summary [data-activity-icon="refine"]')).toBeVisible();
  const solveBox = (await solve.boundingBox())!, refineBox = (await refine.boundingBox())!;
  expect(refineBox.y - solveBox.y - solveBox.height).toBeGreaterThanOrEqual(0);
  expect(refineBox.y - solveBox.y - solveBox.height).toBeLessThanOrEqual(6);
  expect(await page.locator('[data-chat-block]').evaluateAll(els => els.filter(el => el.getBoundingClientRect().height === 0).length)).toBe(0);
  const chevron = summary.locator(".activity-chevron");
  await page.mouse.move(1, 1);
  await expect(chevron).toHaveCSS("opacity", "0");
  await summary.hover();
  await expect(chevron).toHaveCSS("opacity", "0.75");
  const labelBox = await summary.locator(".activity-label").boundingBox();
  const arrowBox = await chevron.boundingBox();
  expect(arrowBox!.x - labelBox!.x - labelBox!.width).toBeLessThan(10);
  expect(arrowBox!.x).toBeGreaterThan(labelBox!.x);
  const proseSize = await page.locator(".agent-message .md").first().evaluate(el => getComputedStyle(el).fontSize);
  await expect(summary).toHaveCSS("font-size", proseSize);
  await expect(page.getByTestId("assistant-copy")).toHaveCount(1);
  await expect(page.locator('[data-final="false"] [data-testid="assistant-copy"]')).toHaveCount(0);
  await page.getByTestId("assistant-copy").getByRole("button").click();
  expect(await page.evaluate(() => (window as unknown as { designClipboard: string }).designClipboard)).toContain("展示验证完成");
  await page.getByTestId("user-copy").getByRole("button").click();
  expect(await page.evaluate(() => (window as unknown as { designClipboard: string }).designClipboard)).toContain("界面验收样本");
  const group = page.locator("details.activity-group").first();
  await expect(group).not.toHaveAttribute("open", "");
  await group.locator(":scope > summary").click();
  await expect(group).toHaveAttribute("open", "");
  // All original command output remains available through nested folds.
  await page.getByRole("button", { name: S.viewVerbose, exact: true }).click();
  await expect(page.getByText("data_specimen", { exact: false })).toBeVisible();
  await expect(page.locator('[data-testid="command-row"] [data-activity-icon="book"]').first()).toBeVisible();
  await expect(page.locator('[data-testid="command-row"] [data-activity-icon="search"]').first()).toBeVisible();
  const failure = page.locator('[data-testid="command-row"][data-status="failed"]');
  await expect(failure.locator(".activity-issue")).toBeVisible();
  await expect(failure).not.toHaveClass(/danger/);
  for (const row of await page.locator('[data-testid="tool-row"] > summary, [data-testid="command-row"] > summary').all()) {
    expect(await row.innerText()).not.toMatch(/12\.345|98\.765|12\.3\s*s|98\.8\s*s/);
  }
  await page.getByRole("button", { name: S.viewConcise, exact: true }).click();
  await page.screenshot({ path: shotPath("transcript-scientific-concise") });
  expect(errors.pageErrors).toEqual([]);
});

test("tool and command shimmer pauses when hidden, respects reduced motion, and stops on completion", async ({ page }) => {
  const liveTool = { kind: "tool_started", ts: ts + 2, server: "crystalpilot", tool: "inspect_map", args: {}, status: "in_progress", duration_ms: null, ok: null, result_tail: null, error: null };
  const liveCommand = { kind: "command_started", ts: ts + 3, command: "cat specimen.cif", item_id: "running-command", status: "in_progress" };
  await fixture(page, [completed[0], completed[1], liveTool, liveCommand]);
  const shimmer = page.locator('[data-testid="tool-row"] .shimmer-text');
  await expect(shimmer).toHaveCSS("animation-name", "shimmer-sweep");
  await expect(page.locator('[data-testid="command-row"] .shimmer-text')).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(shimmer).toHaveCSS("animation-play-state", "paused");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(shimmer).toHaveCSS("background-image", "none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.evaluate(({ tool, time }) => {
    const emit = (window as unknown as { emitDesign: (e: object) => void }).emitDesign;
    emit(tool);
    emit({ kind: "command_completed", ts: time + 5, command: "cat specimen.cif", item_id: "running-command", status: "completed", exit_code: 0, output_tail: "data_specimen" });
    emit({ kind: "agent_message", ts: time + 6, text: "已完成展示样本。" });
    emit({ kind: "turn_completed", ts: time + 7, status: "completed", duration_ms: 7000 });
  }, { tool: call("inspect_map", { diff_map_max: 0.42, diff_map_min: -0.27 }, 4), time: ts });
  await expect(page.locator(".shimmer-text")).toHaveCount(0);
  await expect(page.getByTestId("assistant-copy")).toHaveCount(1);
});

test("both collapsed panels reserve header space and can reopen at desktop and phone widths", async ({ page }) => {
  await fixture(page);
  await page.getByTestId("sidebar-collapse").click();
  await page.getByTestId("right-collapse").click();
  await expect(page.getByTestId("left-panel-transition")).toHaveCount(0);
  await expect(page.getByTestId("right-panel-transition")).toHaveCount(0);
  const header = page.getByTestId("workbench-header");
  const left = page.getByTestId("sidebar-expand");
  const right = page.getByTestId("right-expand");
  const h1 = header.locator("h1");
  const l = (await left.boundingBox())!, r = (await right.boundingBox())!, title = (await h1.boundingBox())!;
  expect(l.x + l.width).toBeLessThanOrEqual(title.x);
  expect(title.x + title.width).toBeLessThanOrEqual(r.x);
  for (const button of [left, right]) expect(await button.evaluate(el => { const b = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2)); })).toBe(true);
  await page.screenshot({ path: shotPath("transcript-both-panels-collapsed") });
  await right.click();
  await page.getByTestId("focus-toggle").click();
  await expect(page.locator('aside[data-focus="1"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByTestId("right-collapse").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await right.click();
  await expect(page.getByTestId("mobile-structure-pane")).toBeVisible();
  await page.getByTestId("right-collapse").click();
  await left.click();
  await expect(page.getByTestId("sidebar-collapse")).toBeVisible();
  await page.getByTestId("sidebar-collapse").click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: shotPath("transcript-mobile") });
});

test("panels ease through intermediate widths, reverse smoothly and respect reduced motion", async ({ page }) => {
  await fixture(page);
  await page.getByRole('group', { name: S.shell.rightPaneTabs }).getByRole('button', { name: new RegExp("^" + rx(S.tabMetrics)) }).click();
  for (const side of ['left', 'right'] as const) {
    const close = side === 'left' ? 'sidebar-collapse' : 'right-collapse';
    const expand = side === 'left' ? 'sidebar-expand' : 'right-expand';
    const measurements = await page.evaluate(async ({ side, close }) => {
      const panel = document.querySelector<HTMLElement>(`[data-testid="${side}-panel-transition"]`)!;
      const width = panel.getBoundingClientRect().width;
      const easing = getComputedStyle(panel).transitionTimingFunction;
      (document.querySelector(`[data-testid="${close}"]`) as HTMLElement).click();
      const widths = [width], start = performance.now();
      while (performance.now() - start < 380) {
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        widths.push(panel.getBoundingClientRect().width);
      }
      return { widths, easing };
    }, { side, close });
    expect(measurements.easing).toContain('cubic-bezier');
    expect(measurements.widths.some(w => w > 1 && w < measurements.widths[0] - 1)).toBe(true);
    await expect(page.getByTestId(`${side}-panel-transition`)).toHaveCount(0);
    await page.getByTestId(expand).click();
    await expect(page.getByTestId(close)).toBeVisible();
    // Reverse two transitions without waiting for either to finish.
    await page.getByTestId(close).evaluate((el: HTMLElement) => el.click());
    await page.getByTestId(expand).evaluate((el: HTMLElement) => el.click());
    await expect(page.getByTestId(`${side}-panel-transition`)).toHaveAttribute('data-expanded', 'true');
    await page.waitForTimeout(350);
    await expect(page.getByTestId(close)).toBeVisible();
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect.poll(() => page.getByTestId('left-panel-transition').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration))).toBeLessThan(0.001);
  await page.getByTestId('sidebar-collapse').click();
  await expect(page.getByTestId('left-panel-transition')).toHaveCount(0);
  await page.getByTestId('sidebar-expand').click();
  await expect(page.getByTestId('sidebar-collapse')).toBeVisible();
});

test("model search and node references remain available", async ({ page }) => {
  await fixture(page, [{ ...completed[0], text: "查看结构引用 [anchor node=n0000]" }, ...completed.slice(1)]);
  const anchor = page.getByTestId("anchor-chip");
  await expect(anchor).toBeVisible();
  await anchor.click();
  await expect(page.locator('aside canvas').first()).toBeVisible();
  await page.getByTestId("model-button").click();
  const search = page.getByPlaceholder(S.modelSearch);
  await expect(search).toBeVisible();
  await search.fill("gpt-5.6-sol");
  await expect(page.getByRole("dialog").getByRole("button").filter({ hasText: /gpt-5.6-sol/i }).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(search).not.toBeVisible();
});
