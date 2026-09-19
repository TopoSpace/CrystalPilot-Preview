/** Real source-bound matrix with independently specified scientific decisions. */
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { shotPath, watchErrors } from "./helpers";

interface Case {
  name: string;
  project: string;
  node: string;
  baseline: string;
  metrics: Record<"r1" | "wr2" | "goof", "comparable" | "different" | "unknown">;
}
const file = process.env.CP_COMPARISON_CASES;
const cases: Case[] = file ? JSON.parse(fs.readFileSync(file, "utf8")) : [];

for (const entry of cases) {
  test(`real comparison oracle: ${entry.name}`, async ({ page, request }) => {
    const query = new URLSearchParams({ project: entry.project });
    const before = await (await request.get(`/api/wb/refine/nodes?${query}`)).json();
    const response = await request.get(`/api/wb/refine/comparison?${query}&node=${entry.node}&baseline=${entry.baseline}`);
    expect(response.ok()).toBe(true);
    const data = await response.json();
    for (const metric of ["r1", "wr2", "goof"] as const) expect(data.metrics[metric].status).toBe(entry.metrics[metric]);
    const errors = watchErrors(page);
    const writes: string[] = [];
    await page.route("**/api/**", (route) => {
      const r = route.request();
      const path = new URL(r.url()).pathname;
      if (["GET", "HEAD", "OPTIONS"].includes(r.method()) || (r.method() === "POST" && path === "/api/projects/open")) return route.continue();
      writes.push(`${r.method()} ${path}`);
      return route.abort();
    });
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto(`/?${query}&view=structure&tab=nodes&focus=1`);
    await page.getByRole("button", { name: `查看节点 ${entry.node}`, exact: true }).click();
    await page.locator(`[data-comparison-node="${entry.baseline}"]`).click();
    const panel = page.getByTestId("structure-comparison");
    await expect(panel).toHaveAttribute("data-node", entry.node);
    await expect(panel).toHaveAttribute("data-baseline", entry.baseline);
    await expect(page.getByTestId("structure-viewport").locator("canvas").first()).toBeVisible();
    for (const metric of ["r1", "wr2", "goof"] as const) {
      const row = panel.getByTestId(`comparison-${metric}`);
      const comparable = entry.metrics[metric] === "comparable";
      await expect(row).toHaveAttribute("data-comparable", String(comparable));
      if (!comparable) await expect(row.locator(".text-ok, .text-danger")).toHaveCount(0);
    }
    await page.getByRole("button", { name: `查看基线 ${entry.baseline}`, exact: true }).click();
    await expect(panel).toContainText(`${entry.baseline} · 绘制`);
    await page.screenshot({ path: shotPath(`oracle-${entry.name}`) });
    const after = await (await request.get(`/api/wb/refine/nodes?${query}`)).json();
    expect(after.active_node).toBe(before.active_node);
    expect(after.nodes).toEqual(before.nodes);
    expect(writes).toEqual([]);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}
