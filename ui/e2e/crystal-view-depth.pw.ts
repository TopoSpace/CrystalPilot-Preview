import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { projectUrl, watchErrors } from "./helpers";

const PROJECT = process.env.CP_CIF_PROJECT ?? "";

interface NodesResponse {
  active_node: string;
  nodes: { id: string; structure_only?: boolean }[];
}

interface SceneResponse {
  mode: string;
  range?: { n_tiles: number; tiles: number[][] };
  sym_elements?: unknown[];
}

async function assertRealCifProject(request: APIRequestContext): Promise<void> {
  const response = await request.get(
    `/api/wb/refine/nodes?project=${encodeURIComponent(PROJECT)}`,
  );
  expect(response.ok()).toBe(true);
  const body = await response.json() as NodesResponse;
  const active = body.nodes.find((node) => node.id === body.active_node);
  expect(active?.structure_only).toBe(true);
}

async function openStructure(page: Page): Promise<ReturnType<typeof watchErrors>> {
  const errors = watchErrors(page);
  await page.goto(`${projectUrl(PROJECT)}&view=structure`);
  await expect(page.getByTestId("structure-only-notice")).toBeVisible();
  await expect(page.locator("aside canvas").first()).toBeVisible({ timeout: 60_000 });
  return errors;
}

test.beforeEach(async ({ request }) => {
  test.skip(!PROJECT, "set CP_CIF_PROJECT to a real CIF-only project");
  await assertRealCifProject(request);
});

test("real CIF camera depth controls change and reset", async ({ page }) => {
  const errors = await openStructure(page);
  const pane = page.locator("aside");

  const viewButton = pane.getByRole("button", { name: "视图", exact: true });
  await expect(viewButton).toBeVisible();
  await viewButton.click();
  await expect(viewButton).toHaveAttribute("aria-expanded", "true");

  const fog = pane.getByRole("button", { name: "远雾", exact: true });
  const clip = pane.getByRole("slider", { name: "前后裁切", exact: true });
  const reset = pane.getByRole("button", { name: "重置", exact: true });
  await expect(fog).toHaveAttribute("aria-pressed", "false");
  await expect(clip).toHaveValue("100");
  await expect(reset).toBeDisabled();

  await fog.click();
  await expect(fog).toHaveAttribute("aria-pressed", "true");
  const fogStart = pane.getByRole("slider", { name: "远雾起点", exact: true });
  await expect(fogStart).toHaveValue("55");

  await clip.press("Home");
  for (let i = 0; i < 5; i += 1) await clip.press("ArrowRight");
  await expect(clip).toHaveValue("35");
  await fogStart.press("End");
  await fogStart.press("ArrowLeft");
  await fogStart.press("ArrowLeft");
  await expect(fogStart).toHaveValue("80");
  await expect(reset).toBeEnabled();

  await reset.click();
  await expect(fog).toHaveAttribute("aria-pressed", "false");
  await expect(clip).toHaveValue("100");
  await expect(fogStart).toHaveCount(0);
  await expect(reset).toBeDisabled();
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});

test("real CIF supercell reports symmetry coverage 8/N", async ({ page }) => {
  const errors = await openStructure(page);
  const pane = page.locator("aside");
  const extentMenu = pane.locator('button[aria-haspopup="menu"]').first();

  await extentMenu.click();
  const supercellResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.ok()
      && url.pathname === "/api/wb/refine/scene"
      && url.searchParams.get("mode") === "supercell"
      && url.searchParams.get("n") === "4";
  });
  await pane.getByRole("menuitem", { name: /^超胞 4×4×4/ }).click();
  const scene = await (await supercellResponse).json() as SceneResponse;
  expect(scene.mode).toBe("supercell");
  expect(scene.range?.n_tiles).toBeGreaterThan(8);
  expect(scene.range?.tiles.length).toBeLessThanOrEqual(64);
  expect(scene.sym_elements?.length).toBeGreaterThan(0);

  const relations = pane.getByRole("button", { name: "关系", exact: true });
  await relations.click();
  await expect(relations).toHaveAttribute("aria-expanded", "true");
  const symmetry = pane.getByRole("button", { name: "对称元素", exact: true });
  await symmetry.click();
  await expect(symmetry).toHaveAttribute("aria-pressed", "true");
  await expect(
    pane.getByText(`对称 8/${scene.range!.n_tiles} 胞`, { exact: true }),
  ).toBeVisible();
  expect(errors.pageErrors).toEqual([]);
  expect(errors.consoleErrors).toEqual([]);
});
