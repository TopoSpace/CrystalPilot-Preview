/** 2026-09-08 usertest follow-up: a geometry-only node (add/delete atoms,
 * hydrogens, mask, twin) has no R factors of its own; the header used to
 * show "—" and the user read it as "the refinement was lost". Now the
 * nearest measured ancestor's numbers are shown dimmed and named
 * ("沿用 nXXXX"). Runs against a REAL project copy (CP_E2E_PROJECT), never
 * a synthetic node tree. */
import { expect, test } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";
import { S } from "./lang";

const PROJECT = process.env.CP_E2E_PROJECT ?? "";

interface NodeRow {
  id: string;
  tool: string;
  r1: number | null;
  metrics_inherited?: { from: string; distance: number; r1: number | null } | null;
}

test("geometry-only node shows the inherited R factors, named", async ({ page, request }) => {
  test.skip(!PROJECT, "set CP_E2E_PROJECT to a real project with geometry-only nodes");
  const response = await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(PROJECT)}`);
  expect(response.ok()).toBe(true);
  const body = await response.json() as { nodes: NodeRow[] };
  const inherited = body.nodes.find((n) => n.r1 === null && n.metrics_inherited?.r1 != null);
  test.skip(!inherited, "no geometry-only node with a measured ancestor in this project");
  const target = inherited!;
  const from = target.metrics_inherited!.from;
  const own = body.nodes.find((n) => n.id === from)!;
  expect(own.r1).toBe(target.metrics_inherited!.r1);

  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  // the project route with the crystal pane focused on the node tree
  // (same entry the comparison-oracle spec uses)
  await page.goto(`${projectUrl(PROJECT)}&view=structure&tab=nodes&focus=1`);
  await expect(page.getByTestId("node-tree")).toBeVisible({ timeout: 60_000 });
  // unfold every folded branch and the diagnostic group so the row exists
  for (const sel of ['[data-testid="tree-branch"][data-folded="1"]', '[data-testid="tree-diag"][aria-expanded="false"]']) {
    const folded = page.locator(sel);
    const n = await folded.count();
    for (let i = 0; i < n; i += 1) await folded.nth(0).click();
  }
  const row = page.getByRole("button", { name: S.crystal.viewNodeAria(target.id), exact: true });
  await row.scrollIntoViewIfNeeded();
  await row.click();
  // the header's own chip (the node tree rows carry their own "沿用" text
  // already; the header used to show "—" beside them)
  const chip = page.getByTitle(S.headerInheritedTip).first();
  await expect(chip).toBeVisible();
  await expect(chip).toContainText(`${S.headerInherited} ${from}`);
  // the number shown is the ancestor's (dimmed on the stat itself)
  const r1Text = own.r1!.toFixed(4);
  await expect(page.locator("aside").getByText(r1Text, { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: shotPath(`handover-header-inherited-${target.id}`) });
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});
