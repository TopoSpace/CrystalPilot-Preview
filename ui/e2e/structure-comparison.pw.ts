/** Real GET-backed structure comparison. Only project-open registration may POST.
 * Synthetic condition responses are explicitly named fixtures, not provenance acceptance.
 * CP_COMPARE_REQUIRE_BOUND=1 requires the parent-created version-bound scientific pair.
 */
import { expect, test, type Page, type APIRequestContext } from "@playwright/test";
import type { NodeComparisonResponse, NodeComparisonSource, NodesResponse, RefineNode } from "../src/lib/wbTypes";
import { comparableMetric, comparisonNumber } from "../src/lib/structureComparison";
import { shotPath, watchErrors } from "./helpers";

const project = process.env.CP_E2E_PROJECT ?? "";
const baselineId = process.env.CP_COMPARE_BASELINE ?? "n0002";
const nodeId = process.env.CP_COMPARE_NODE ?? "n0004";
const requireBound = process.env.CP_COMPARE_REQUIRE_BOUND === "1";
const query = () => `project=${encodeURIComponent(project)}`;
const forbidden = new WeakMap<Page, string[]>();

async function nodes(request: APIRequestContext): Promise<NodesResponse> {
  const response = await request.get(`/api/wb/refine/nodes?${query()}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function openComparison(page: Page) {
  const errors = watchErrors(page);
  await page.goto(`/?${query()}&view=structure&tab=nodes&focus=1`);
  await page.getByRole("button", { name: `查看节点 ${nodeId}`, exact: true }).click();
  const entry = page.locator(`[data-comparison-node="${baselineId}"]`);
  await entry.focus();
  await entry.press("Enter");
  const panel = page.getByTestId("structure-comparison");
  await expect(panel).toHaveAttribute("data-node", nodeId);
  await expect(panel).toHaveAttribute("data-baseline", baselineId);
  await expect(panel).toContainText(`${nodeId} · 绘制`);
  const canvas = page.getByTestId("structure-viewport").locator("canvas").first();
  await expect(canvas).toBeVisible();
  await expect.poll(() => canvas.evaluate((element) => {
    const source = element as HTMLCanvasElement;
    const copy = document.createElement("canvas");
    copy.width = source.width; copy.height = source.height;
    const context = copy.getContext("2d")!;
    context.drawImage(source, 0, 0);
    const pixels = context.getImageData(0, 0, copy.width, copy.height).data;
    let count = 0;
    for (let index = 4; index < pixels.length; index += 4) {
      if (pixels[index + 3] > 0 && Math.max(Math.abs(pixels[index] - pixels[0]),
        Math.abs(pixels[index + 1] - pixels[1]), Math.abs(pixels[index + 2] - pixels[2])) > 20) count++;
    }
    return count;
  })).toBeGreaterThan(100);
  return errors;
}

async function side(page: Page, id: string) {
  await page.getByRole("button", { name: `查看${id === baselineId ? "基线" : "对比"} ${id}`, exact: true }).click();
  await expect(page.getByTestId("structure-comparison")).toContainText(`${id} · 绘制`);
}

async function observeViewer(page: Page) {
  const response = await page.request.get("/src/workbench/crystal/CrystalViewer.tsx");
  const source = await response.text();
  const moduleUrl = source.match(/from "([^"]*\/3dmol\.js[^"]*)"/)?.[1];
  test.skip(!moduleUrl, "public viewer observation requires Vite, not the production static bundle");
  await page.evaluate(async (url) => {
    const imported = await import(/* @vite-ignore */ url);
    const mol = imported.default ?? imported;
    const original = mol.GLViewer.prototype.zoomTo;
    mol.GLViewer.prototype.zoomTo = function (...args: unknown[]) {
      (window as any).comparisonTestViewer = this;
      (window as any).comparisonTestFitCalls = ((window as any).comparisonTestFitCalls ?? 0) + 1;
      return original.apply(this, args);
    };
  }, moduleUrl!);
  await page.getByTitle("重置视角", { exact: true }).click();
  await expect.poll(() => page.evaluate(() => !!(window as any).comparisonTestViewer)).toBe(true);
  await page.waitForTimeout(600); // existing ResizeObserver trailing-fit window
}

async function pickFirstRealAtom(page: Page) {
  await page.evaluate(() => {
    const viewer = (window as any).comparisonTestViewer;
    const atom = viewer.getModel().selectedAtoms({}).find((item: any) => typeof item.callback === "function");
    if (!atom) throw new Error("real selectable atom required");
    atom.callback(atom, viewer);
  });
}

function syntheticSource(node: RefineNode): NodeComparisonSource {
  return { node: node.id, model_revision: node.revision ?? null, data_revision: "synthetic-fixture-only",
    data_binding: "bound", metrics_current: node.metrics_current,
    metrics_source: { node: node.id, model_revision: node.revision ?? null, data_revision: "synthetic-fixture-only",
      engine: "synthetic-condition-fixture", job: null, conditions_token: "fixture" },
    conditions_token: "fixture", conditions: null,
    frame: { revision: "synthetic-frame", cell: null, space_group_operations: null },
    evidence: { reflection_recompute: false, reason: "synthetic-fixture-no-recompute" },
  };
}

function syntheticDecision(before: RefineNode, after: RefineNode): NodeComparisonResponse {
  return { schema: 1, node: after.id, baseline: before.id, project_revision: 1,
    sources: { node: syntheticSource(after), baseline: syntheticSource(before) },
    metrics: { r1: { status: "comparable", reasons: [] }, wr2: { status: "different", reasons: ["weighting"] }, goof: { status: "different", reasons: ["weighting"] } },
    frame: { status: "compatible", reasons: ["synthetic-camera-fixture"] },
    differences: [{ field: "weighting", node: "synthetic B", baseline: "synthetic A" }], unknown_fields: [],
  };
}

test.beforeEach(async ({ page }) => {
  test.skip(!project, "requires an authorized real CP_E2E_PROJECT");
  forbidden.set(page, []);
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (["GET", "HEAD", "OPTIONS"].includes(request.method()) || (request.method() === "POST" && path === "/api/projects/open")) return route.continue();
    forbidden.get(page)!.push(`${request.method()} ${path}`);
    return route.abort();
  });
});

test.afterEach(async ({ page }) => { expect(forbidden.get(page) ?? []).toEqual([]); });

test("real pair stays read-only, reports node facts, quotes both sources and restores focus", async ({ page, request }) => {
  const before = await nodes(request);
  const current = before.nodes.find((node) => node.id === nodeId)!;
  const baseline = before.nodes.find((node) => node.id === baselineId)!;
  expect(current).toBeTruthy(); expect(baseline).toBeTruthy();
  const errors = await openComparison(page);
  const panel = page.getByTestId("structure-comparison");
  await expect(panel.getByTestId("comparison-r1")).toContainText(comparisonNumber(current.r1, 4));
  await expect(panel.getByTestId("comparison-r1")).toContainText(comparisonNumber(baseline.r1, 4));
  const asu = panel.getByRole("row").filter({ hasText: "模型 ASU" });
  await expect(asu).toContainText(String(current.n_atoms));
  await expect(asu).toContainText(String(baseline.n_atoms));
  const response = await request.get(`/api/wb/refine/comparison?${query()}&node=${nodeId}&baseline=${baselineId}`);
  const data = response.ok() ? await response.json().catch(() => null) as NodeComparisonResponse | null : null;
  if (requireBound) {
    expect(response.ok()).toBe(true);
    expect(data?.sources.node.data_binding).toBe("bound");
    expect(data?.sources.baseline.data_binding).toBe("bound");
  }
  for (const metric of ["r1", "wr2", "goof"] as const) {
    await expect(panel.getByTestId(`comparison-${metric}`)).toHaveAttribute("data-comparable", String(comparableMetric(data, metric, current, baseline)));
  }
  if (!data || data.sources.node.data_binding === "legacy_unknown") {
    await expect(panel).toHaveAttribute("data-comparability", "unknown");
    await expect(panel.locator(".text-ok, .text-danger")).toHaveCount(0);
  }
  await side(page, baselineId);
  await panel.getByRole("button", { name: "引用对比", exact: true }).press("Space");
  await expect(page.locator("textarea").first()).toHaveValue(new RegExp(`\\[anchor node=${baselineId}`));
  const draft = await page.locator("textarea").first().inputValue();
  expect(draft).toContain(`[anchor node=${baselineId}`);
  expect(draft).toContain(`[anchor node=${nodeId}`);
  expect(draft).toContain(comparisonNumber(current.r1, 4));
  await panel.getByRole("button", { name: "退出对比", exact: true }).click();
  await expect(page.locator(`[data-comparison-node="${baselineId}"]`)).toBeFocused();
  const after = await nodes(request);
  expect(after.active_node).toBe(before.active_node);
  expect(after.nodes).toEqual(before.nodes);
  expect(errors.pageErrors).toEqual([]);
});

test("real renderer retains one canvas and independent per-node selection and cameras", async ({ page }) => {
  const errors = await openComparison(page);
  await observeViewer(page);
  const canvas = page.getByTestId("structure-viewport").locator("canvas").first();
  await canvas.evaluate((element) => { element.setAttribute("data-comparison-probe", "retained"); });
  await pickFirstRealAtom(page);
  await expect(page.getByTestId("atom-selection")).toHaveAttribute("data-node", nodeId);
  const originalView = await page.evaluate(() => {
    const viewer = (window as any).comparisonTestViewer;
    viewer.rotate(27, "y"); viewer.zoom(0.85); viewer.render();
    return viewer.getView();
  });
  await side(page, baselineId);
  await expect(page.getByTestId("atom-selection")).toHaveCount(0);
  await page.evaluate(() => { const viewer = (window as any).comparisonTestViewer; viewer.rotate(-17, "x"); viewer.render(); });
  await pickFirstRealAtom(page);
  await expect(page.getByTestId("atom-selection")).toHaveAttribute("data-node", baselineId);
  await side(page, nodeId);
  await expect(canvas).toHaveAttribute("data-comparison-probe", "retained");
  await expect(page.getByTestId("atom-selection")).toHaveAttribute("data-node", nodeId);
  const decision = await page.request.get(`/api/wb/refine/comparison?${query()}&node=${nodeId}&baseline=${baselineId}`);
  const decisionData = decision.ok() ? await decision.json().catch(() => null) : null;
  const compatible = decisionData?.frame.status === "compatible";
  if (!compatible) {
    const restored = await page.evaluate(() => (window as any).comparisonTestViewer.getView());
    restored.forEach((value: number, index: number) => expect(value).toBeCloseTo(originalView[index], 8));
  }
  await page.getByTestId("atom-selection").getByRole("button", { name: "在对话中引用", exact: true }).click();
  await expect(page.locator("textarea").first()).toHaveValue(new RegExp(`\\[anchor node=${nodeId}`));
  expect(errors.pageErrors).toEqual([]);
});

test("real renderer fits an uncached extent instead of saving the ASU camera under its key", async ({ page }) => {
  const errors = await openComparison(page);
  await observeViewer(page);
  await page.waitForTimeout(200); // beyond the existing 700ms initial-fit arm
  const before = await page.evaluate(() => {
    const viewer = (window as any).comparisonTestViewer;
    viewer.zoom(1.4); viewer.render();
    return { fits: (window as any).comparisonTestFitCalls, view: viewer.getView() };
  });
  await page.locator('aside button[aria-haspopup="menu"]').first().click();
  const scene = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.ok() && url.pathname === "/api/wb/refine/scene" && url.searchParams.get("mode") === "supercell";
  });
  await page.getByRole("menuitem", { name: /^超胞 2×2×2/ }).click();
  await scene;
  await expect(page.getByTestId("structure-comparison")).toContainText(`${nodeId} · 绘制`);
  await expect.poll(() => page.evaluate(() => (window as any).comparisonTestFitCalls)).toBeGreaterThan(before.fits);
  const after = await page.evaluate(() => (window as any).comparisonTestViewer.getView());
  expect(after).not.toEqual(before.view);
  expect(errors.pageErrors).toEqual([]);
});

test("synthetic per-metric condition fixture gates colours without replacing real model facts", async ({ page, request }) => {
  const real = await nodes(request);
  const current = real.nodes.find((node) => node.id === nodeId)!;
  const baseline = real.nodes.find((node) => node.id === baselineId)!;
  const fixture = syntheticDecision(baseline, current);
  await page.route("**/api/wb/refine/comparison?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("node") === nodeId && url.searchParams.get("baseline") === baselineId)
      return route.fulfill({ json: fixture });
    return route.continue();
  });
  await openComparison(page);
  const panel = page.getByTestId("structure-comparison");
  await expect(panel.getByTestId("comparison-r1")).toHaveAttribute("data-comparable", String(current.metrics_current && baseline.metrics_current));
  await expect(panel.getByTestId("comparison-wr2")).toHaveAttribute("data-comparable", "false");
  await expect(panel.getByTestId("comparison-goof")).toHaveAttribute("data-comparable", "false");
  await expect(panel.getByTestId("comparison-goof").locator(".text-ok, .text-danger")).toHaveCount(0);
  await expect(panel).toContainText("相机同步 · 选择独立");
});

test("synthetic wrong-pair response fixture remains neutral and cannot relabel sources", async ({ page, request }) => {
  const real = await nodes(request);
  const current = real.nodes.find((node) => node.id === nodeId)!;
  const baseline = real.nodes.find((node) => node.id === baselineId)!;
  const fixture = syntheticDecision(baseline, current);
  fixture.baseline = "n9999";
  await page.route("**/api/wb/refine/comparison?**", (route) => route.fulfill({ json: fixture }));
  await openComparison(page);
  const panel = page.getByTestId("structure-comparison");
  await expect(panel).toHaveAttribute("data-comparability", "unknown");
  await expect(panel.locator(".text-ok, .text-danger")).toHaveCount(0);
  await expect(panel).not.toContainText("n9999");
});

test("synthetic delayed scene delivery fixture cannot expose an old-node quote", async ({ page, request }) => {
  const realScene = await request.get(`/api/wb/refine/scene?${query()}&node=${baselineId}&mode=asu&diff=0&polyhedra=1`);
  expect(realScene.ok()).toBe(true);
  const json = await realScene.json();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/wb/refine/scene?**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("node") !== baselineId) return route.continue();
    await gate;
    await route.fulfill({ json }).catch(() => undefined); // deliberately late after abort
  });
  await openComparison(page);
  await observeViewer(page);
  await pickFirstRealAtom(page);
  await expect(page.getByTestId("atom-selection")).toHaveAttribute("data-node", nodeId);
  await page.getByRole("button", { name: `查看基线 ${baselineId}`, exact: true }).click();
  await expect(page.getByTestId("structure-comparison")).toContainText(`正在加载 ${baselineId}`);
  await expect(page.getByTestId("atom-selection")).toHaveCount(0);
  await side(page, nodeId);
  release();
  await expect(page.getByTestId("atom-selection")).toHaveAttribute("data-node", nodeId);
  await page.getByTestId("atom-selection").getByRole("button", { name: "在对话中引用", exact: true }).click();
  await expect(page.locator("textarea").first()).toHaveValue(new RegExp(`\\[anchor node=${nodeId}`));
});

const layouts = [
  [390, 720, "kimi", "dark", 16],
  [900, 720, "anthropic", "light", 13],
  [1100, 800, "kimi", "light", 15],
  [1366, 900, "openai", "dark", 16],
  [1920, 1080, "openai", "light", 14],
] as const;
for (const [width, height, palette, theme, font] of layouts) {
  test(`real comparison layout ${width} ${palette} ${theme} font ${font}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(({ palette, theme, font }) => {
      localStorage.setItem("crystalpilot-palette", palette);
      localStorage.setItem("crystalpilot-theme", theme);
      localStorage.setItem("crystalpilot-font-size", String(font));
    }, { palette, theme, font });
    const errors = await openComparison(page);
    const panel = page.getByTestId("structure-comparison");
    const box = (await page.getByTestId("structure-viewport").boundingBox())!;
    expect(box.height).toBeGreaterThan(120);
    expect(box.width).toBeGreaterThan(260);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await panel.getByRole("button", { name: /^查看基线 / }).press("ArrowRight");
    await expect(panel.getByRole("button", { name: /^查看对比 / })).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: shotPath(`comparison-${width}-${palette}-${theme}`) });
    expect(errors.pageErrors).toEqual([]);
  });
}
