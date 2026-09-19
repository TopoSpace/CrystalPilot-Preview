/** Check the served application and build time; no commit/digest comparison. */
import { expect, test } from "@playwright/test";

interface UiBuild {
  present: boolean;
  stale?: boolean;
  built_at?: string;
  version?: string | null;
  src_newest_file?: string | null;
}

test("served UI build is fresh", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.ok()).toBeTruthy();
  const body = (await res.json()) as { ok: boolean; ui_build?: UiBuild };
  expect(body.ok).toBe(true);
  const b = body.ui_build;
  expect(b?.present, "ui/dist is served").toBe(true);
  test.info().annotations.push({ type: "ui_build", description: JSON.stringify(b) });
  expect(
    b?.stale,
    `dist is older than ${b?.src_newest_file ?? "a source file"} - run npm run build and restart`,
  ).toBe(false);

  expect(b?.built_at).toBeTruthy();
});
