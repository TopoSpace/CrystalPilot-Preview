/** Round-3 R6 evidence: the question card (transcript card + composer dock
 * that answers with a `[prior]` message), steer receipts (已送达模型 /
 * 未送达模型 + 重试), anchor chips that jump the crystal pane to the quoted
 * node, quote chips in the composer, and the knowledge-mode / structure-
 * class rows of the settings menu.
 *
 * UI EVIDENCE ONLY: the page is a REAL project, but the transcript is the
 * real one with a clearly synthetic tail appended by a route mock (a card,
 * two steers with receipts), and the send/steer endpoints are mocked so no
 * message reaches the model. Screenshots land in workdir/ui-evidence/<round>/.
 * Run:
 *   CP_EVIDENCE_ROUND=r3-r6 CP_E2E_PROJECT=<path> npx playwright test e2e/r6-interaction.pw.ts */
import { expect, test, type Page } from "@playwright/test";
import { pickTarget, setTheme, shotPath, THEMES, threadUrl, watchErrors, type Target } from "./helpers";
import { S, rx } from "./lang";

const CARD =
  "骨架已稳定（R1 0.085）。\n\n```ask\n" +
  JSON.stringify({
    settled: "已确认 P6/mmm，Zr6 簇由两组重原子峰支持",
    dispute: "孔内 Q1 3.2 eÅ⁻³ 距 O3 2.1 Å：可能是对溴苯乙酸的 Br，也可能是无序 DMF",
    question: "合成时是否加入了对溴苯乙酸？",
    options: ["有", "没有", "不知道"],
    fallback: "不知道则按溶剂掩膜处理，客体假设进 open_directions",
  }) +
  "\n```\n";

async function settle(page: Page, ms = 800): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(ms);
}

interface Ev {
  kind: string;
  eid?: number;
  [k: string]: unknown;
}

for (const theme of THEMES) {
  test.describe(`R6 interaction (${theme})`, () => {
    let target: Target | null = null;
    let anchorNode = "n0001";
    test.beforeAll(async ({ request }) => {
      target = await pickTarget(request);
      if (target === null) return;
      const r = await request.get(`/api/wb/refine/nodes?project=${encodeURIComponent(target.project)}`);
      if (r.ok()) {
        const j = (await r.json()) as { active_node?: string | null; nodes?: { id: string }[] };
        // a node other than the active one, so the jump is visibly a history view
        const other = (j.nodes ?? []).find((n) => n.id !== j.active_node);
        anchorNode = other?.id ?? j.active_node ?? "n0001";
      }
    });

    test("question card, receipts, anchor jump, quote chips, settings", async ({ page }) => {
      test.skip(target === null, "no real project with a node tree");
      test.setTimeout(180_000);
      await page.setViewportSize({ width: 1440, height: 900 });
      await setTheme(page, theme);
      const errors = watchErrors(page);

      // the real transcript + a synthetic tail (evidence for the renderer)
      await page.route(
        (u) => u.pathname === "/api/threads/transcript",
        async (route) => {
          const res = await route.fetch();
          const json = (await res.json()) as { events?: Ev[]; total?: number; live_cursor?: number };
          const events = json.events ?? [];
          let eid = Math.max(json.total ?? 0, ...events.map((e) => e.eid ?? 0));
          const ts0 = Date.now() / 1000;
          const push = (ev: Record<string, unknown>): number => {
            eid += 1;
            events.push({ ...ev, ts: ts0 + eid / 1000, eid } as Ev);
            return eid;
          };
          const u1 = push({
            kind: "user_message",
            text: `请看 ${anchorNode} 的 O1 周围 [anchor node=${anchorNode} atoms=O1]`,
            steer: true,
          });
          push({ kind: "steer_receipt", steer_eid: u1, status: "submitted" });
          const u2 = push({ kind: "user_message", text: "先别删 O5，换个方向再试", steer: true });
          push({
            kind: "steer_receipt",
            steer_eid: u2,
            status: "failed",
            error: "RuntimeError: turn/steer: turn already completed",
          });
          push({ kind: "agent_message", text: CARD });
          json.events = events;
          json.total = eid;
          await route.fulfill({ json });
        },
      );
      // nothing reaches the model: the answer is captured here instead
      let sent: string | null = null;
      await page.route(
        (u) => u.pathname === "/api/threads/send" || u.pathname === "/api/threads/steer",
        async (route) => {
          const body = route.request().postDataJSON() as { message?: string };
          sent = body.message ?? null;
          await route.fulfill({
            json: { ok: true, thread_id: target!.threadId, task_id: "task_mock", receipt: "submitted" },
          });
        },
      );

      await page.goto(threadUrl(target!));
      const pane = page.locator("aside");
      await expect(pane.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
      await settle(page, 1500);

      // 1. the card: in the transcript and docked above the composer
      const dock = page.getByTestId("ask-dock");
      await expect(dock).toBeVisible();
      await expect(dock).toContainText("合成时是否加入了对溴苯乙酸");
      await expect(dock).toContainText("不知道则按溶剂掩膜处理");
      expect(await page.getByTestId("ask-card").count()).toBeGreaterThan(0);

      // 2. receipts on the two steers
      const submitted = page.locator('[data-testid="user-bubble"][data-receipt="submitted"]').last();
      await expect(submitted).toContainText(S.receiptSubmitted);
      const failed = page.locator('[data-testid="user-bubble"][data-receipt="failed"]').last();
      await expect(failed).toContainText(S.receiptFailed);
      await expect(failed.getByRole("button", { name: S.receiptRetry })).toBeVisible();
      await page.screenshot({ path: shotPath(`r6-${theme}-card-receipts`) });

      // 3. one click answers: a [prior] message, then the dock closes
      await dock.getByRole("button", { name: "有", exact: true }).click();
      await expect.poll(() => sent).toBe(S.libs.askPriorReply("[prior]", "合成时是否加入了对溴苯乙酸？", "有"));
      await expect(dock).toHaveCount(0);

      // 4. the anchor chip jumps the crystal pane to the quoted node (history view)
      const chip = page.getByTestId("anchor-chip").first();
      await expect(chip).toBeVisible();
      await chip.click();
      await settle(page, 1500);
      await expect(pane.getByTestId("identity-row1")).toContainText(anchorNode);
      await page.screenshot({ path: shotPath(`r6-${theme}-anchor-jump`) });

      // 5. quote chips in the composer: removable, the text stays the truth
      const ta = page.locator("textarea").first();
      await ta.fill(`看看 [anchor node=${anchorNode} atoms=O1] 附近的密度`);
      const rail = page.getByTestId("anchor-rail");
      await expect(rail).toBeVisible();
      await expect(rail).toContainText(anchorNode);
      await page.screenshot({ path: shotPath(`r6-${theme}-quote-chip`) });
      await rail.getByRole("button", { name: S.anchorRemove }).click();
      await expect(ta).toHaveValue("看看 附近的密度");
      await expect(rail).toHaveCount(0);
      await ta.fill("");

      // 6. settings menu: knowledge mode + structure class rows
      const permissionLabels = [S.permReadonly, S.permCopilot, S.permAuto, S.permFull].map(rx).join("|");
      await page.getByRole("button", { name: new RegExp(`^(${permissionLabels})$`) }).first().click();
      await expect(page.getByTestId("settings-knowledge-mode")).toBeVisible();
      await expect(page.getByTestId("settings-structure-class")).toBeVisible();
      await expect(page.getByTestId("settings-knowledge-mode").locator("select")).toHaveValue(/full|tools_only/);
      await page.screenshot({ path: shotPath(`r6-${theme}-settings`) });
      await page.keyboard.press("Escape");

      expect(errors.pageErrors).toEqual([]);
    });
  });
}
