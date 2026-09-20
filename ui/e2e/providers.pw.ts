/** Real provider UX. A temporary unauthenticated provider is saved then removed;
 * no real credentials, remote probes or model requests are used. */
import { expect, test } from "@playwright/test";
import { projectUrl, shotPath, watchErrors } from "./helpers";
import { S } from "./lang";

for (const width of [1366, 390]) {
  test(`provider configuration at ${width}px`, async ({ page, request }) => {
    const rows = await (await request.get("/api/projects/status")).json() as { path: string; n_nodes?: number }[];
    const project = process.env.CP_CIF_PROJECT ?? rows.find((row) => (row.n_nodes ?? 0) > 0)?.path;
    test.skip(!project, "the real server has no usable structure project");
    const errors = watchErrors(page);
    const writes: string[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET" && new URL(r.url()).pathname.startsWith("/api/providers")) writes.push(r.url());
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto(projectUrl(project!));
    if (!(await page.getByTestId("open-settings").isVisible())) {
      await page.getByRole("button", { name: S.sidebarOpen, exact: true }).click();
    }
    await page.getByTestId("open-settings").click();
    const dialog = page.getByTestId("settings-dialog");
    const list = dialog.getByTestId("provider-list");
    await expect(list.getByTestId("provider-crystalpilot")).toBeVisible();
    await expect(list.getByTestId("provider-openrouter")).toBeVisible();
    expect(await dialog.innerText()).not.toMatch(/sk-[A-Za-z0-9_-]{10,}/);
    await page.screenshot({ path: shotPath(`providers-${width}-list`) });

    await dialog.getByTestId("provider-add").click();
    const form = dialog.getByTestId("provider-form");
    await form.getByRole("button", { name: "Responses-compatible", exact: true }).click();
    await expect(form.getByTestId("provider-id")).toHaveValue("");
    await expect(form.getByTestId("provider-base-url")).toHaveValue("");
    await expect(form.getByTestId("provider-protocol")).toHaveValue("responses");
    await expect(form.getByTestId("provider-auth-mode")).toHaveValue("managed_api_key");
    const protocols = form.getByTestId("provider-protocol").locator("option");
    await expect(protocols).toHaveCount(4);
    for (const i of [1, 2, 3]) await expect(protocols.nth(i)).toHaveJSProperty("disabled", true);
    await expect(form.getByTestId("provider-key")).toHaveValue("");
    await form.getByTestId("provider-base-url").fill("http://127.0.0.1:9/v1");
    await expect(form.getByTestId("provider-test")).toBeEnabled();
    await form.getByTestId("provider-auth-mode").selectOption("environment");
    await expect(form.getByTestId("provider-test")).toBeDisabled();
    await form.getByTestId("provider-advanced").locator("summary").click();
    await expect(form).toContainText(S.providerIdleTimeout);
    expect(await form.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: shotPath(`providers-${width}-advanced`) });
    expect(writes).toEqual([]);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  });
}

test("save advanced settings through the real UI and remove only the test provider", async ({ page, request }) => {
  const id = `e2e-save-${Date.now()}`;
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1366, height: 900 });
  try {
    await page.goto("/");
    await page.getByTestId("open-settings").click();
    await page.getByTestId("provider-add").click();
    const form = page.getByTestId("provider-form");
    await form.getByTestId("provider-id").fill(id);
    await form.getByRole("textbox", { name: S.providerName, exact: true }).fill("配置保存回归");
    await form.getByTestId("provider-base-url").fill("http://127.0.0.1:9/v1");
    await form.getByTestId("provider-auth-mode").selectOption("none");
    await form.getByTestId("provider-advanced").locator("summary").click();
    await form.getByRole("spinbutton", { name: S.providerRequestRetries, exact: true }).fill("3");
    await form.getByRole("spinbutton", { name: S.providerIdleTimeout, exact: true }).fill("45000");
    const saved = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/providers");
    await form.getByTestId("provider-save").click();
    expect((await saved).status()).toBe(200);
    await expect(form).toHaveCount(0);
    await expect(page.getByTestId(`provider-${id}`)).toBeVisible();
    const response = await request.get("/api/providers");
    const body = await response.json();
    const provider = body.providers.find((p: { id: string }) => p.id === id);
    expect(provider.auth_mode).toBe("none");
    expect(provider.request_max_retries).toBe(3);
    expect(provider.stream_idle_timeout_ms).toBe(45000);
    expect(body.providers.some((p: { id: string }) => p.id === "crystalpilot")).toBe(true);
    expect(body.providers.some((p: { id: string }) => p.id === "openrouter")).toBe(true);
    expect(errors.pageErrors).toEqual([]);
    expect(errors.consoleErrors).toEqual([]);
  } finally {
    const removed = await request.delete(`/api/providers/${id}`);
    expect([200, 404]).toContain(removed.status());
  }
});
